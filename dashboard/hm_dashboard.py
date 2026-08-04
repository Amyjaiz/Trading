from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from threading import Lock, Thread

import pyotp
from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from flask_socketio import SocketIO, disconnect, emit
from werkzeug.security import check_password_hash, generate_password_hash

# ──────────────────────────────────────────────────────────────
# CONFIGURATION — update these paths for your Windows machine
# ──────────────────────────────────────────────────────────────
TRIPLE_SCREEN_DIR    = r"C:\Trade\triple_screen"
NSE200_DIR           = r"C:\Trade\nse200"
HM_DIR               = r"C:\Trade\hm"
DASHBOARD_DIR        = os.path.dirname(os.path.abspath(__file__))

AUTH_FILE            = os.path.join(DASHBOARD_DIR, "dashboard_auth.json")
CUSTOM_UNIVERSE_FILE = os.path.join(DASHBOARD_DIR, "custom_universe.json")
ORDER_LOG_FILE       = os.path.join(DASHBOARD_DIR, "order_log.csv")

TRADING_ENABLED      = False       # flip to True to send live orders
MAX_ORDER_VALUE      = 25_000      # hard cap per order in ₹
LOGIN_TOTP_REQUIRED  = False       # TEMP: dashboard login TOTP disabled — password only.
                                    # Does NOT affect order placement, which always re-verifies
                                    # TOTP via _verify_totp() in api_order() regardless of this flag.

# Angel One credentials (hardcoded per Aman's preference — fill these in)
ANGEL_API_KEY        = "your_api_key"
ANGEL_CLIENT_ID      = "your_client_id"
ANGEL_PASSWORD       = "your_mpin"
ANGEL_TOTP_SECRET    = "your_totp_seed"   # Angel One's own TOTP seed

# ──────────────────────────────────────────────────────────────
# Flask + SocketIO — threading mode only (no eventlet)
# ──────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.urandom(32)   # sessions invalidated on restart (intentional)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

_backtest_procs:  dict[str, subprocess.Popen | None] = {"hm": None, "ts": None, "nse": None}
_backtest_status: dict[str, str]                     = {"hm": "idle", "ts": "idle", "nse": "idle"}
_backtest_locks:  dict[str, Lock]                    = {"hm": Lock(), "ts": Lock(), "nse": Lock()}

# ──────────────────────────────────────────────────────────────
# Auth helpers
# ──────────────────────────────────────────────────────────────
def _load_auth() -> dict:
    if not os.path.exists(AUTH_FILE):
        return {}
    with open(AUTH_FILE) as f:
        return json.load(f)

def _save_auth(data: dict) -> None:
    with open(AUTH_FILE, "w") as f:
        json.dump(data, f, indent=2)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login_page"))
        if time.time() - session.get("last_active", 0) > 1800:   # 30 min inactivity
            session.clear()
            return redirect(url_for("login_page"))
        session["last_active"] = time.time()
        return f(*args, **kwargs)
    return wrapper

def _verify_totp(code: str) -> bool:
    auth = _load_auth()
    secret = auth.get("totp_secret", "")
    if not secret:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)

# ──────────────────────────────────────────────────────────────
# File readers
# ──────────────────────────────────────────────────────────────
def _read_json(path: str) -> dict | list:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _read_csv_dicts(path: str) -> list[dict]:
    try:
        with open(path, newline="", errors="replace") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def _read_ts_filter_config() -> dict:
    """Reads the NIFTY_REGIME_FILTER / ML_FILTER_ENABLED toggles straight out
    of live_trading_bot_final.py's source — these are plain constants set at
    the top of the script, not written to any state file, so parse them
    directly rather than requiring the bot to export a status file."""
    path = os.path.join(TRIPLE_SCREEN_DIR, "live_trading_bot_final.py")
    result = {"nifty_regime_filter": None, "ml_filter_enabled": None}
    try:
        with open(path, errors="replace") as f:
            src = f.read()
        m = re.search(r"^NIFTY_REGIME_FILTER\s*=\s*(True|False)", src, re.MULTILINE)
        if m:
            result["nifty_regime_filter"] = m.group(1) == "True"
        m = re.search(r"^ML_FILTER_ENABLED\s*=\s*(True|False)", src, re.MULTILINE)
        if m:
            result["ml_filter_enabled"] = m.group(1) == "True"
    except Exception:
        pass
    return result

def _bot_log_tail(bot_dir: str, n: int = 50) -> tuple[list[str], float]:
    log_path = os.path.join(bot_dir, "bot.log")
    lines: list[str] = []
    lag = float("inf")
    try:
        lag = time.time() - os.path.getmtime(log_path)
        with open(log_path, errors="replace") as f:
            all_lines = f.readlines()
        lines = [ln.rstrip() for ln in all_lines[-n:]]
    except Exception:
        pass
    return lines, lag

# ──────────────────────────────────────────────────────────────
# Bot state readers
# ──────────────────────────────────────────────────────────────
def read_hm_positions() -> list[dict]:
    data = _read_json(os.path.join(HM_DIR, "positions.json"))
    return list(data.values()) if isinstance(data, dict) else []

def read_ts_positions() -> list[dict]:
    return _read_csv_dicts(os.path.join(TRIPLE_SCREEN_DIR, "open_positions.csv"))

def read_nse200_signals() -> list[dict]:
    rows = _read_csv_dicts(os.path.join(NSE200_DIR, "nse200_signal_log.csv"))
    seen: dict[str, dict] = {}
    for row in reversed(rows):
        sym = row.get("ticker", "")
        if sym and sym not in seen:
            seen[sym] = row
    return list(seen.values())

def read_custom_universe() -> dict:
    default = {
        "hm":            {"add": [], "remove": []},
        "triple_screen": {"add": [], "remove": []},
        "nse200":        {"extra": []},
    }
    if not os.path.exists(CUSTOM_UNIVERSE_FILE):
        return default
    try:
        with open(CUSTOM_UNIVERSE_FILE) as f:
            return json.load(f)
    except Exception:
        return default

def write_custom_universe(data: dict) -> None:
    with open(CUSTOM_UNIVERSE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ──────────────────────────────────────────────────────────────
# Market data
# ──────────────────────────────────────────────────────────────
def _base_symbol(symbol: str) -> str:
    return symbol[:-3] if symbol.upper().endswith(".NS") else symbol

def _get_ltps(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    bases = [_base_symbol(s) for s in symbols]
    try:
        import yfinance as yf
        tickers = [s + ".NS" for s in bases]
        if len(tickers) == 1:
            data = yf.download(tickers[0], period="1d", interval="1m",
                               progress=False, auto_adjust=True)
            close = data["Close"].dropna()
            return {symbols[0]: round(float(close.iloc[-1]), 2)} if not close.empty else {}
        data = yf.download(tickers, period="1d", interval="1m",
                           progress=False, auto_adjust=True)
        prices: dict[str, float] = {}
        close = data["Close"]
        base_to_orig = dict(zip(bases, symbols))
        for col in close.columns:
            sym = str(col).replace(".NS", "")
            series = close[col].dropna()
            if not series.empty:
                prices[base_to_orig.get(sym, sym)] = round(float(series.iloc[-1]), 2)
        return prices
    except Exception:
        return {}

def _get_sparkline(symbol: str) -> list[float]:
    try:
        import yfinance as yf
        df = yf.download(_base_symbol(symbol) + ".NS", period="30d", interval="1d",
                         progress=False, auto_adjust=True)
        return [round(float(x), 2) for x in df["Close"].dropna().tolist()]
    except Exception:
        return []

# ──────────────────────────────────────────────────────────────
# Angel One
# ──────────────────────────────────────────────────────────────
def _angel_login():
    from SmartApi import SmartConnect
    api = SmartConnect(api_key=ANGEL_API_KEY)
    totp_code = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
    api.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp_code)
    return api

def _get_angel_balance() -> float | None:
    try:
        api = _angel_login()
        r = api.rmsLimit()
        return float(r["data"]["availablecash"])
    except Exception:
        return None

def _load_token_map() -> dict[str, str]:
    for d in [HM_DIR, TRIPLE_SCREEN_DIR]:
        path = os.path.join(d, "angel_tokens.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

def _place_order(symbol: str, txn: str, qty: int) -> dict:
    if not TRADING_ENABLED:
        return {
            "status": "simulated",
            "symbol": symbol, "txn": txn, "qty": qty,
            "message": "TRADING_ENABLED=False — order not sent to exchange",
        }
    token_map = _load_token_map()
    token = token_map.get(symbol, "")
    try:
        api = _angel_login()
        result = api.placeOrder({
            "variety":         "NORMAL",
            "tradingsymbol":   symbol + "-EQ",
            "symboltoken":     token,
            "transactiontype": txn,
            "exchange":        "NSE",
            "ordertype":       "MARKET",
            "producttype":     "DELIVERY",
            "duration":        "DAY",
            "quantity":        str(qty),
        })
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ──────────────────────────────────────────────────────────────
# Trade analytics
# ──────────────────────────────────────────────────────────────
PERIOD_DAYS: dict[str, int | None] = {
    "1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365, "all": None,
}

def _read_hm_live_trades() -> list[dict]:
    """hm_live_bot.py logs entries/exits to live_trades.csv (real orders) or
    paper_trades.csv (TRADING_ENABLED=False) — NOT hm_trades.csv, which is the
    backtest script's output file and gets overwritten by every backtest run.
    Both live/paper files share one header row but BUY and SELL rows populate
    the same column positions with different meanings (e.g. col 7 is order_id
    on a BUY row, pnl on a SELL row), so DictReader would misparse SELL rows.
    Parse by position instead."""
    path = None
    for fname in ("live_trades.csv", "paper_trades.csv"):
        candidate = os.path.join(HM_DIR, fname)
        if os.path.exists(candidate):
            path = candidate
            break
    if not path:
        return []
    rows: list[dict] = []
    try:
        with open(path, newline="", errors="replace") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for r in reader:
                if len(r) < 12:
                    continue
                ts, action = r[0], r[1].upper()
                if action == "SELL":
                    price, entry_px, pnl, pnl_pct, held, reason = r[5], r[6], r[7], r[8], r[9], r[10]
                else:
                    price, entry_px, pnl, pnl_pct, held, reason = r[5], "", "0", "0", "0", r[11] if len(r) > 11 else ""
                rows.append({
                    "date":      ts[:10],
                    "time":      ts[11:19] if len(ts) > 19 else "",
                    "action":    action,
                    "symbol":    r[2],
                    "sector":    r[3],
                    "qty":       r[4],
                    "price":     price,
                    "entry_px":  entry_px,
                    "pnl":       pnl,
                    "pnl_pct":   pnl_pct,
                    "held_days": held,
                    "reason":    reason,
                    "model":     "HM",
                })
    except Exception:
        pass
    return rows

def _all_trades(bot_filter: str = "all", period_days: int | None = None) -> list[dict]:
    sources = [
        ("TS",  os.path.join(TRIPLE_SCREEN_DIR, "ts_trades.csv")),
        ("MOM", os.path.join(NSE200_DIR,        "nse200_trades.csv")),
    ]
    cutoff = (datetime.now() - timedelta(days=period_days)).date() if period_days else None
    trades: list[dict] = []
    for tag, path in sources:
        if bot_filter not in ("all", tag.lower()):
            continue
        for row in _read_csv_dicts(path):
            if cutoff:
                try:
                    if datetime.strptime(row.get("date", ""), "%Y-%m-%d").date() < cutoff:
                        continue
                except Exception:
                    pass
            row["_bot"] = tag
            trades.append(row)
    if bot_filter in ("all", "hm"):
        for row in _read_hm_live_trades():
            if cutoff:
                try:
                    if datetime.strptime(row.get("date", ""), "%Y-%m-%d").date() < cutoff:
                        continue
                except Exception:
                    pass
            row["_bot"] = "HM"
            trades.append(row)
    return trades

def _compute_analytics(trades: list[dict]) -> dict:
    sells = [t for t in trades if t.get("action", "").upper() in ("SELL", "EXIT")]
    if not sells:
        return {"total_pnl": 0, "win_rate": 0, "total_trades": 0,
                "profit_factor": 0, "avg_hold": 0,
                "best_trade": {}, "worst_trade": {}}
    pnls: list[float] = []
    holds: list[int] = []
    for t in sells:
        try:
            pnls.append(float(t.get("pnl", 0) or 0))
        except Exception:
            pnls.append(0.0)
        try:
            holds.append(int(t.get("held_days", 0) or 0))
        except Exception:
            pass
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))

    def safe_pct(row: dict) -> float:
        try:
            return float(row.get("pnl_pct", 0) or 0)
        except Exception:
            return 0.0

    best  = max(sells, key=safe_pct, default={})
    worst = min(sells, key=safe_pct, default={})
    return {
        "total_pnl":    round(sum(pnls), 2),
        "win_rate":     round(100 * len(wins) / len(pnls), 1) if pnls else 0,
        "total_trades": len(pnls),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else 0,
        "avg_hold":     round(sum(holds) / len(holds), 1) if holds else 0,
        "best_trade":  {"symbol": best.get("symbol"),  "pct": best.get("pnl_pct")},
        "worst_trade": {"symbol": worst.get("symbol"), "pct": worst.get("pnl_pct")},
    }

def _pair_round_trips(trades: list[dict]) -> list[dict]:
    """Pair each SELL/EXIT row with its FIFO-matching BUY row (per bot+symbol)
    into one row per completed round trip, so History shows entry and exit
    together instead of as two separate rows at different times."""
    groups: dict[tuple, list[dict]] = {}
    for t in trades:
        groups.setdefault((t.get("_bot", ""), t.get("symbol", "")), []).append(t)

    closed: list[dict] = []
    for (bot, symbol), rows in groups.items():
        rows.sort(key=lambda t: (t.get("date", ""), t.get("time", "")))
        pending: list[dict] = []
        for t in rows:
            action = (t.get("action") or "").upper()
            if action == "BUY":
                pending.append(t)
            elif action in ("SELL", "EXIT"):
                entry = pending.pop(0) if pending else None
                try:
                    pnl = float(t.get("pnl", 0) or 0)
                except Exception:
                    pnl = 0.0
                closed.append({
                    "_bot":       bot,
                    "symbol":     symbol,
                    "entry_date": entry.get("date") if entry else None,
                    "entry_time": entry.get("time") if entry else None,
                    "exit_date":  t.get("date"),
                    "exit_time":  t.get("time"),
                    "date":       t.get("date"),   # for _compute_analytics compatibility
                    "action":     "SELL",
                    "qty":        t.get("qty"),
                    "buy_price":  (entry.get("price") if entry else None) or t.get("entry_px"),
                    "sell_price": t.get("price"),
                    "pnl":        pnl,
                    "pnl_pct":    t.get("pnl_pct"),
                    "held_days":  t.get("held_days"),
                    "reason":     t.get("reason"),
                })
    closed.sort(key=lambda t: (t.get("exit_date") or "", t.get("exit_time") or ""), reverse=True)
    return closed

def _win_rate_for_symbol(symbol: str) -> str:
    wins = losses = 0
    for path in [os.path.join(TRIPLE_SCREEN_DIR, "ts_trades.csv"),
                 os.path.join(NSE200_DIR,        "nse200_trades.csv")]:
        for row in _read_csv_dicts(path):
            if row.get("symbol") == symbol and row.get("action", "").upper() in ("SELL", "EXIT"):
                if float(row.get("pnl", 0) or 0) > 0:
                    wins += 1
                else:
                    losses += 1
    for row in _read_hm_live_trades():
        if row.get("symbol") == symbol and row.get("action", "").upper() == "SELL":
            if float(row.get("pnl", 0) or 0) > 0:
                wins += 1
            else:
                losses += 1
    total = wins + losses
    if total == 0:
        return "—"
    return f"{wins}W/{losses}L = {round(100*wins/total)}%"

# ──────────────────────────────────────────────────────────────
# Background price push loop (every 10 s)
# ──────────────────────────────────────────────────────────────
def _price_push_loop() -> None:
    while True:
        try:
            syms = list({
                *(p.get("symbol", "") for p in read_hm_positions()),
                *(p.get("Symbol", "") for p in read_ts_positions()),
                *(p.get("ticker", "") for p in read_nse200_signals()),
            } - {""})
            if syms:
                ltps = _get_ltps(syms)
                socketio.emit("prices_update", ltps)
        except Exception:
            pass
        time.sleep(10)

# ──────────────────────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    if request.method == "POST":
        pw   = request.form.get("password", "")
        totp = request.form.get("totp", "")
        auth = _load_auth()
        if not auth:
            error = "Auth not set up. Run: python hm_dashboard.py --set-password"
        else:
            time.sleep(1)   # brute-force protection
            pw_ok   = check_password_hash(auth.get("pw_hash", "x"), pw)
            totp_ok = True if not LOGIN_TOTP_REQUIRED else \
                pyotp.TOTP(auth.get("totp_secret", "x")).verify(totp, valid_window=1)
            if pw_ok and totp_ok:
                session.clear()
                session["authenticated"] = True
                session["last_active"]   = time.time()
                return redirect(url_for("overview"))
            error = "Invalid password or authenticator code."
    return render_template("login.html", error=error, login_totp_required=LOGIN_TOTP_REQUIRED)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

# ──────────────────────────────────────────────────────────────
# Page routes
# ──────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def overview():
    return render_template("overview.html", page="overview",
                           trading_enabled=TRADING_ENABLED)

@app.route("/positions")
@login_required
def positions():
    return render_template("positions.html", page="positions",
                           trading_enabled=TRADING_ENABLED)

@app.route("/backtest")
@login_required
def backtest():
    return render_template("backtest.html", page="backtest")

@app.route("/universe")
@login_required
def universe():
    return render_template("universe.html", page="universe")

@app.route("/history")
@login_required
def history():
    return render_template("history.html", page="history")

@app.route("/logs")
@login_required
def logs():
    return render_template("logs.html", page="logs")

# ──────────────────────────────────────────────────────────────
# API — Overview
# ──────────────────────────────────────────────────────────────
@app.route("/api/overview")
@login_required
def api_overview():
    hm_pos  = read_hm_positions()
    ts_pos  = read_ts_positions()
    nse_pos = read_nse200_signals()

    all_syms = list({
        *(p.get("symbol", "")  for p in hm_pos),
        *(p.get("Symbol", "")  for p in ts_pos),
        *(p.get("ticker", "")  for p in nse_pos),
    } - {""})
    ltps = _get_ltps(all_syms)

    unreal = 0.0
    for p in hm_pos:
        sym = p.get("symbol", "")
        try:
            unreal += (ltps.get(sym, 0) - float(p.get("entry_px", 0))) * int(p.get("qty", 0))
        except Exception:
            pass
    for p in ts_pos:
        sym = p.get("Symbol", "")
        try:
            unreal += (ltps.get(sym, 0) - float(p.get("BuyPrice", 0))) * int(p.get("Qty", 0))
        except Exception:
            pass

    def bot_health(bot_dir: str, name: str) -> dict:
        lines, lag = _bot_log_tail(bot_dir, 3)
        if lag < 120:
            status = "active"
        elif lag < 600:
            status = "idle"
        else:
            status = "offline"
        return {
            "name":       name,
            "status":     status,
            "lag_s":      int(lag) if lag != float("inf") else None,
            "last_lines": lines[-3:],
        }

    today = datetime.now().strftime("%Y-%m-%d")
    today_trades: list[dict] = []
    for tag, path in [
        ("TS",  os.path.join(TRIPLE_SCREEN_DIR, "ts_trades.csv")),
        ("MOM", os.path.join(NSE200_DIR,        "nse200_trades.csv")),
    ]:
        for row in _read_csv_dicts(path):
            if row.get("date", "") == today:
                row["_bot"] = tag
                today_trades.append(row)
    for row in _read_hm_live_trades():
        if row.get("date", "") == today:
            row["_bot"] = "HM"
            today_trades.append(row)

    all_trades   = _all_trades("all", None)
    realized     = _compute_analytics(all_trades)
    realized_pnl = realized["total_pnl"]

    recent_sells = [t for t in all_trades if t.get("action", "").upper() in ("SELL", "EXIT")]
    recent_sells.sort(key=lambda t: t.get("date", ""), reverse=True)
    recent_trades = recent_sells[:15]

    return jsonify({
        "available_cash":     _get_angel_balance(),
        "unrealised_pnl":     round(unreal, 2),
        "realized_pnl":       realized_pnl,
        "total_pnl":          round(unreal + realized_pnl, 2),
        "realized_win_rate":  realized["win_rate"],
        "realized_trades":    realized["total_trades"],
        "open_positions":  len(hm_pos) + len(ts_pos) + len(nse_pos),
        "bots": {
            "ts":  {**bot_health(TRIPLE_SCREEN_DIR, "Triple Screen"), **_read_ts_filter_config()},
            "mom": bot_health(NSE200_DIR,        "NSE200 Momentum"),
            "hm":  bot_health(HM_DIR,            "Hilega Milega"),
        },
        "today_trades":  today_trades,
        "recent_trades": recent_trades,
    })

# ──────────────────────────────────────────────────────────────
# API — Positions
# ──────────────────────────────────────────────────────────────
@app.route("/api/positions")
@login_required
def api_positions():
    hm_pos  = read_hm_positions()
    ts_pos  = read_ts_positions()
    nse_pos = read_nse200_signals()
    all_syms = list({
        *(p.get("symbol", "") for p in hm_pos),
        *(p.get("Symbol", "") for p in ts_pos),
        *(p.get("ticker", "") for p in nse_pos),
    } - {""})
    ltps = _get_ltps(all_syms)

    def enrich_hm(p: dict) -> dict:
        sym   = p.get("symbol", "")
        ltp   = ltps.get(sym, 0.0)
        entry = float(p.get("entry_px", 0) or 0)
        qty   = int(p.get("qty", 0) or 0)
        pnl_pct = round(100 * (ltp - entry) / entry, 2) if entry else 0
        return {**p, "ltp": ltp, "pnl_pct": pnl_pct,
                "pnl_rs": round((ltp - entry) * qty, 2),
                "win_rate": _win_rate_for_symbol(sym)}

    def enrich_ts(p: dict) -> dict:
        sym   = p.get("Symbol", "")
        ltp   = ltps.get(sym, 0.0)
        entry = float(p.get("BuyPrice", 0) or 0)
        qty   = int(p.get("Qty", 0) or 0)
        pnl_pct = round(100 * (ltp - entry) / entry, 2) if entry else 0
        return {**p, "ltp": ltp, "pnl_pct": pnl_pct,
                "pnl_rs": round((ltp - entry) * qty, 2),
                "win_rate": _win_rate_for_symbol(sym)}

    def enrich_nse(p: dict) -> dict:
        sym   = p.get("ticker", "")
        ltp   = ltps.get(sym, 0.0)
        entry = float(p.get("price", 0) or 0)
        qty   = int(p.get("qty", 0) or 0)
        pnl_pct = round(100 * (ltp - entry) / entry, 2) if entry else 0
        return {**p, "ltp": ltp, "pnl_pct": pnl_pct,
                "pnl_rs": round((ltp - entry) * qty, 2),
                "win_rate": _win_rate_for_symbol(sym)}

    return jsonify({
        "hm":  [enrich_hm(p)  for p in hm_pos],
        "ts":  [enrich_ts(p)  for p in ts_pos],
        "nse": [enrich_nse(p) for p in nse_pos],
    })

@app.route("/api/sparkline/<symbol>")
@login_required
def api_sparkline(symbol: str):
    return jsonify(_get_sparkline(symbol.upper()))

# ──────────────────────────────────────────────────────────────
# API — Orders (TOTP required on every order)
# ──────────────────────────────────────────────────────────────
@app.route("/api/order", methods=["POST"])
@login_required
def api_order():
    data   = request.get_json(force=True)
    symbol = str(data.get("symbol", "")).upper()
    txn    = str(data.get("txn", "")).upper()
    totp   = str(data.get("totp", ""))
    try:
        qty = int(data.get("qty", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "rejected", "message": "qty must be an integer"}), 400

    if not _verify_totp(totp):
        return jsonify({"status": "rejected", "message": "Invalid authenticator code"}), 403
    if txn not in ("BUY", "SELL"):
        return jsonify({"status": "rejected", "message": "txn must be BUY or SELL"}), 400
    if qty <= 0:
        return jsonify({"status": "rejected", "message": "qty must be positive"}), 400

    result = _place_order(symbol, txn, qty)

    with open(ORDER_LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(), request.remote_addr,
            symbol, txn, qty, result.get("status"), "totp_verified",
        ])
    return jsonify(result)

# ──────────────────────────────────────────────────────────────
# API — Backtest subprocess (per-model concurrent execution)
# ──────────────────────────────────────────────────────────────
_BACKTEST_SCRIPTS = {
    "hm":  (HM_DIR,            "hm_backtest.py"),
    "ts":  (TRIPLE_SCREEN_DIR, "ts_backtest.py"),
    "nse": (NSE200_DIR,        "nse200_backtest.py"),
}

@app.route("/api/backtest/run", methods=["POST"])
@login_required
def api_backtest_run():
    data    = request.get_json(force=True)
    model   = str(data.get("model", "hm")).lower()
    stocks  = [str(s).upper() for s in data.get("stocks", [])]
    start   = str(data.get("start", ""))
    capital = str(data.get("capital", ""))
    flags   = [str(f) for f in data.get("flags", [])]

    if model not in _BACKTEST_SCRIPTS:
        return jsonify({"status": "error", "message": f"Unknown model: {model}"}), 400

    # Incorporate custom universe adds/removes from custom_universe.json
    uni = read_custom_universe()
    model_uni_key = {"hm": "hm", "ts": "triple_screen", "nse": "nse200"}.get(model, model)
    uni_section   = uni.get(model_uni_key, {})
    uni_adds      = [s.upper() for s in uni_section.get("add",   [])]
    uni_removes   = [s.upper() for s in uni_section.get("remove", [])]
    uni_extra     = [s.upper() for s in uni_section.get("extra",  [])]

    lock = _backtest_locks[model]
    with lock:
        proc = _backtest_procs[model]
        if proc and proc.poll() is None:
            return jsonify({"status": "running", "message": f"{model.upper()} backtest already running"})

        bot_dir, script = _BACKTEST_SCRIPTS[model]
        cmd = ["python", script]
        if stocks:
            cmd += ["--stocks"] + stocks
            # Still append extra-stocks/exclude from universe config
            if model == "hm":
                if uni_adds:    cmd += ["--extra-stocks"] + uni_adds
                if uni_removes: cmd += ["--exclude"]      + uni_removes
        else:
            # No explicit filter — apply universe config
            if model == "hm":
                if uni_adds:    cmd += ["--extra-stocks"] + uni_adds
                if uni_removes: cmd += ["--exclude"]      + uni_removes
            elif model == "nse" and (uni_extra or uni_adds):
                extra = list(dict.fromkeys(uni_extra + uni_adds))
                cmd += ["--stocks"] + extra
        if start:
            cmd += ["--start", start]
        if capital:
            cmd += ["--capital", capital]
        cmd += flags

        env  = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.Popen(
            cmd, cwd=bot_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        _backtest_procs[model]  = proc
        _backtest_status[model] = "running"

    def _stream(m: str, p: subprocess.Popen) -> None:
        for line in p.stdout:
            socketio.emit("backtest_output", {"model": m, "line": line.rstrip()})
        p.wait()
        with _backtest_locks[m]:
            _backtest_status[m] = "completed" if p.returncode == 0 else "failed"
        socketio.emit("backtest_done", {"model": m, "returncode": p.returncode})

    Thread(target=_stream, args=(model, proc), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/api/backtest/cancel", methods=["POST"])
@login_required
def api_backtest_cancel():
    data  = request.get_json(force=True) or {}
    model = str(data.get("model", "")).lower()
    models_to_cancel = [model] if model in _backtest_locks else list(_backtest_locks.keys())
    cancelled = []
    for m in models_to_cancel:
        with _backtest_locks[m]:
            proc = _backtest_procs[m]
            if proc and proc.poll() is None:
                proc.terminate()
                _backtest_status[m] = "idle"
                cancelled.append(m)
    if cancelled:
        return jsonify({"status": "cancelled", "models": cancelled})
    return jsonify({"status": "not_running"})

@app.route("/api/backtest/status")
@login_required
def api_backtest_status():
    result = {}
    for m, lock in _backtest_locks.items():
        with lock:
            proc    = _backtest_procs[m]
            running = proc is not None and proc.poll() is None
            result[m] = {
                "running": running,
                "status":  "running" if running else _backtest_status[m],
            }
    return jsonify(result)

@app.route("/api/backtest/results/<model>")
@login_required
def api_backtest_results(model: str):
    csv_map = {
        "hm":  os.path.join(HM_DIR,            "hm_trades.csv"),
        "ts":  os.path.join(TRIPLE_SCREEN_DIR, "ts_backtest_trades.csv"),
        "nse": os.path.join(NSE200_DIR,        "nse200_backtest_trades.csv"),
    }
    path = csv_map.get(model.lower())
    if not path:
        return jsonify({"error": "unknown model"}), 400
    trades = _read_csv_dicts(path)
    # Load pre-computed summary metrics (CAGR/Sharpe/MaxDD require equity curve)
    metrics_map = {
        "hm":  os.path.join(HM_DIR,            "hm_metrics.json"),
        "nse": os.path.join(NSE200_DIR,        "nse200_metrics.json"),
    }
    summary_metrics: dict = {}
    if model.lower() in metrics_map:
        summary_metrics = _read_json(metrics_map[model.lower()])
        if not isinstance(summary_metrics, dict):
            summary_metrics = {}

    per_stock: dict[str, dict] = {}
    for row in trades:
        sym = row.get("symbol", "")
        if not sym:
            continue
        s = per_stock.setdefault(sym, {
            "symbol": sym, "trades": 0, "wins": 0,
            "total_pnl": 0.0, "total_pct": 0.0, "hold_days": 0,
        })
        s["trades"] += 1
        try:
            pnl  = float(row.get("pnl", 0) or 0)
            pct  = float(row.get("pnl_pct", 0) or 0)
            days = int(row.get("held_days", 0) or 0)
            s["total_pnl"] += pnl
            s["total_pct"] += pct
            s["hold_days"] += days
            if pnl > 0:
                s["wins"] += 1
        except Exception:
            pass
    result_list = []
    for sym, s in per_stock.items():
        t = s["trades"]
        result_list.append({
            "symbol":   sym,
            "trades":   t,
            "net_pnl":  round(s["total_pnl"], 2),
            "win_rate": round(100 * s["wins"] / t, 1) if t else 0,
            "avg_ret":  round(s["total_pct"] / t, 2) if t else 0,
            "avg_hold": round(s["hold_days"] / t, 1) if t else 0,
        })
    analytics = _compute_analytics(trades)
    # Overlay CAGR/Sharpe/MaxDD from pre-saved metrics file (can't compute from trades log alone)
    analytics.update({k: summary_metrics[k] for k in ("cagr", "sharpe", "maxdd") if k in summary_metrics})
    return jsonify({"per_stock": result_list, "analytics": analytics})

# ──────────────────────────────────────────────────────────────
# API — Universe manager
# ──────────────────────────────────────────────────────────────
@app.route("/api/universe", methods=["GET"])
@login_required
def api_universe_get():
    return jsonify(read_custom_universe())

@app.route("/api/universe", methods=["POST"])
@login_required
def api_universe_save():
    data = request.get_json(force=True)
    write_custom_universe(data)
    return jsonify({"status": "saved"})

_UNIVERSE_ADD_LOCK    = Lock()
_UNIVERSE_REMOVE_LOCK = Lock()

@app.route("/api/universe/add", methods=["POST"])
@login_required
def api_universe_add():
    data   = request.get_json(force=True)
    bot    = str(data.get("bot", "")).lower()
    symbol = str(data.get("symbol", "")).upper().strip()
    if not symbol or not bot:
        return jsonify({"status": "error", "message": "bot and symbol required"}), 400
    with _UNIVERSE_ADD_LOCK:
        uni = read_custom_universe()
        if bot == "nse200":
            arr = uni.setdefault("nse200", {}).setdefault("extra", [])
        elif bot in ("hm", "triple_screen"):
            arr = uni.setdefault(bot, {}).setdefault("add", [])
        else:
            return jsonify({"status": "error", "message": f"Unknown bot: {bot}"}), 400
        if symbol in arr:
            return jsonify({"status": "already_exists", "bot": bot, "symbol": symbol})
        arr.append(symbol)
        write_custom_universe(uni)
    return jsonify({"status": "added", "bot": bot, "symbol": symbol})

@app.route("/api/universe/remove", methods=["POST"])
@login_required
def api_universe_remove():
    data   = request.get_json(force=True)
    bot    = str(data.get("bot", "")).lower()
    symbol = str(data.get("symbol", "")).upper().strip()
    if not symbol or not bot:
        return jsonify({"status": "error", "message": "bot and symbol required"}), 400
    with _UNIVERSE_REMOVE_LOCK:
        uni = read_custom_universe()
        if bot == "nse200":
            section = uni.setdefault("nse200", {"extra": []})
            arr = section.setdefault("extra", [])
            if symbol in arr:
                arr.remove(symbol)
            else:
                return jsonify({"status": "error", "message": f"{symbol} not in nse200 universe"}), 404
        elif bot in ("hm", "triple_screen"):
            section    = uni.setdefault(bot, {"add": [], "remove": []})
            add_arr    = section.setdefault("add", [])
            remove_arr = section.setdefault("remove", [])
            if symbol in add_arr:
                add_arr.remove(symbol)
            elif symbol in remove_arr:
                remove_arr.remove(symbol)
            else:
                remove_arr.append(symbol)
        else:
            return jsonify({"status": "error", "message": f"Unknown bot: {bot}"}), 400
        write_custom_universe(uni)
    return jsonify({"status": "removed", "bot": bot, "symbol": symbol})

# ──────────────────────────────────────────────────────────────
# API — Trade history
# ──────────────────────────────────────────────────────────────
@app.route("/api/history")
@login_required
def api_history():
    bot    = request.args.get("bot",    "all").lower()
    period = request.args.get("period", "all").lower()
    result = request.args.get("result", "all").lower()
    search = request.args.get("search", "").upper()
    page   = max(1, int(request.args.get("page", 1)))

    # Pair on the FULL unfiltered history first, so a trade's entry is still
    # matched even if it falls outside the selected period window — then
    # filter the resulting closed trades by exit date.
    all_trades = _all_trades(bot, None)
    closed = _pair_round_trips(all_trades)

    period_days = PERIOD_DAYS.get(period)
    if period_days:
        cutoff = (datetime.now() - timedelta(days=period_days)).date()
        def _in_period(t: dict) -> bool:
            try:
                return datetime.strptime(t.get("exit_date") or "", "%Y-%m-%d").date() >= cutoff
            except Exception:
                return False
        closed = [t for t in closed if _in_period(t)]

    if result == "win":
        closed = [t for t in closed if float(t.get("pnl", 0) or 0) > 0]
    elif result == "loss":
        closed = [t for t in closed if float(t.get("pnl", 0) or 0) <= 0]
    elif result == "stop":
        closed = [t for t in closed if "stop" in (t.get("reason") or "").lower()]
    if search:
        closed = [t for t in closed if search in (t.get("symbol") or "").upper()]

    analytics = _compute_analytics(closed)

    per_stock: dict[str, dict] = {}
    for t in closed:
        sym = t.get("symbol", "")
        if not sym:
            continue
        s = per_stock.setdefault(sym, {"symbol": sym, "trades": 0, "wins": 0, "total_pnl": 0.0})
        s["trades"] += 1
        pnl = float(t.get("pnl", 0) or 0)
        s["total_pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
    per_stock_list = [
        {"symbol": sym, "trades": s["trades"], "total_pnl": round(s["total_pnl"], 2),
         "win_rate": round(100 * s["wins"] / s["trades"], 1) if s["trades"] else 0}
        for sym, s in per_stock.items()
    ]

    per_page = 50
    total    = len(closed)
    page_trades = closed[(page - 1) * per_page: page * per_page]

    return jsonify({
        "analytics":  analytics,
        "per_stock":  per_stock_list,
        "trades":     page_trades,
        "total":      total,
        "page":       page,
        "pages":      max(1, (total + per_page - 1) // per_page),
    })

@app.route("/api/history/download")
@login_required
def api_history_download():
    bot    = request.args.get("bot",    "all").lower()
    period = request.args.get("period", "all").lower()
    trades = _all_trades(bot, PERIOD_DAYS.get(period))
    output = io.StringIO()
    if trades:
        writer = csv.DictWriter(output, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=trade_history.csv"})

# ──────────────────────────────────────────────────────────────
# API — Logs
# ──────────────────────────────────────────────────────────────
_BOT_DIRS = {"ts": TRIPLE_SCREEN_DIR, "mom": NSE200_DIR, "hm": HM_DIR}

@app.route("/api/logs/<bot>")
@login_required
def api_logs(bot: str):
    bot_dir = _BOT_DIRS.get(bot.lower())
    if not bot_dir:
        return jsonify({"error": "unknown bot"}), 400
    lines, lag = _bot_log_tail(bot_dir, 50)
    return jsonify({"lines": lines, "lag_s": int(lag) if lag != float("inf") else None})

@app.route("/api/logs/<bot>/download")
@login_required
def api_logs_download(bot: str):
    bot_dir = _BOT_DIRS.get(bot.lower())
    if not bot_dir:
        return jsonify({"error": "unknown bot"}), 400
    log_path = os.path.join(bot_dir, "bot.log")
    return send_file(log_path, as_attachment=True, download_name=f"{bot}_bot.log")

# ──────────────────────────────────────────────────────────────
# WebSocket — reject unauthenticated connections
# ──────────────────────────────────────────────────────────────
@socketio.on("connect")
def ws_connect():
    if not session.get("authenticated"):
        disconnect()
        return False

# ──────────────────────────────────────────────────────────────
# CLI setup commands
# ──────────────────────────────────────────────────────────────
def cmd_set_password() -> None:
    import getpass
    pw1 = getpass.getpass("New dashboard password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw1 != pw2:
        print("Passwords do not match.")
        sys.exit(1)
    auth = _load_auth()
    auth["pw_hash"] = generate_password_hash(pw1)
    _save_auth(auth)
    print("Password saved to dashboard_auth.json")

def cmd_setup_2fa() -> None:
    auth = _load_auth()
    if not auth.get("totp_secret"):
        secret = pyotp.random_base32()
        auth["totp_secret"] = secret
        _save_auth(auth)
    else:
        secret = auth["totp_secret"]
    uri = pyotp.TOTP(secret).provisioning_uri(name="AliveGaming", issuer_name="HM Dashboard")
    print(f"\nTOTP secret: {secret}")
    print(f"\nProvisioning URI:\n{uri}\n")
    try:
        import qrcode
        img = qrcode.make(uri)
        qr_path = os.path.join(DASHBOARD_DIR, "totp_qr.png")
        img.save(qr_path)
        print(f"QR code saved to: {qr_path}")
        print("Scan with Google Authenticator.")
    except ImportError:
        print("Install qrcode[pil] to generate a QR image, or scan the URI above manually.")

# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alive Gaming Trading Dashboard")
    parser.add_argument("--set-password", action="store_true", help="Set dashboard password")
    parser.add_argument("--setup-2fa",    action="store_true", help="Configure Google Authenticator")
    parser.add_argument("--port",         type=int, default=5000, help="Port to listen on")
    args = parser.parse_args()

    if args.set_password:
        cmd_set_password()
        sys.exit(0)
    if args.setup_2fa:
        cmd_setup_2fa()
        sys.exit(0)

    if not _load_auth():
        print("WARNING: Auth not configured. Run:")
        print("  python hm_dashboard.py --set-password")
        print("  python hm_dashboard.py --setup-2fa")

    Thread(target=_price_push_loop, daemon=True).start()
    print(f"Alive Gaming Trading Dashboard starting on http://0.0.0.0:{args.port}")
    print(f"Trading: {'ENABLED' if TRADING_ENABLED else 'DISABLED (paper mode)'}")
    socketio.run(app, host="0.0.0.0", port=args.port, debug=False)
