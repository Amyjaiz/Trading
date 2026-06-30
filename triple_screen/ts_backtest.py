"""
================================================================================
TRIPLE SCREEN DEFENSE — Standalone Backtest
================================================================================
Strategy : Elder's Three-Screen method on NSE equities
           Screen 1: Close > EMA(50)              — weekly trend filter
           Screen 2: RSI(2) < 30 yesterday        — daily pullback trigger
           Screen 3: Per-stock proven trigger      — entry confirmation
               BUY_STOP  : today's close > yesterday's high
               RSI_CROSS : RSI(14) crosses above 40
               FORCE_IDX : Force Index(13) crosses above zero
Sizing   : ATR-based risk — 3% capital risk per trade, 2.5×ATR stop
Regime   : Nifty > 200-SMA to allow new entries
Universe : 313 stocks with per-stock best trigger (proven from original backtest)

COMMANDS:
  python ts_backtest.py                                    # full backtest
  python ts_backtest.py --start 2022-01-01                # custom period
  python ts_backtest.py --capital 200000                  # override capital
  python ts_backtest.py --stocks CGPOWER GRSE IIFL        # focused — seconds not minutes
  python ts_backtest.py --sweep                           # compare trigger modes
  python ts_backtest.py --notrigger                       # ignore per-stock triggers, use all three

OUTPUT:
  ts_trades.csv    — standard trade log (dashboard reads this)
================================================================================
"""

from __future__ import annotations
import argparse
import datetime as dt
import os
import sys
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================================
# CONFIG
# ============================================================================
CFG = dict(
    START       = "2018-01-01",
    END         = None,             # None = today
    CAPITAL     = 100_000.0,
    RISK_PCT    = 0.03,             # 3% risk per trade
    ATR_MULT    = 2.5,              # stop = entry - 2.5×ATR
    MAX_POS     = 7,                # max concurrent positions
    MAX_NEW_DAY = 3,                # max new entries per day
    MIN_PRICE   = 50.0,             # skip stocks below Rs50
    TRADE_CSV   = "ts_trades.csv",
)

# ============================================================================
# UNIVERSE — 313 stocks with per-stock best trigger
# ============================================================================
STOCKS = [
    "NATIONALUM","SYRMA","LAURUSLABS","HINDCOPPER","ABCAPITAL","MUTHOOTFIN",
    "CUB","ASHOKLEY","HEROMOTOCO","RBLBANK","BOSCHLTD","DIXON","FORTIS","IIFL",
    "BEL","HINDALCO","BANKINDIA","THERMAX","UNIONBANK","AUBANK","VEDL","BHEL",
    "PAYTM","INDIANB","POLYCAB","UTIAMC","ADANIPOWER","DBREALTY","DCMSHRIRAM",
    "TVSMOTOR","SBIN","CDSL","KRBL","ECLERX","VIPIND","COFORGE","M&MFIN",
    "EICHERMOT","CRISIL","RAMCOCEM","SUZLON","ZEEL","NAVINFLUOR","CANBK",
    "CHENNPETRO","RADICO","ANGELONE","ZENTEC","JIOFIN","PRESTIGE","MINDSPACE",
    "INDUSTOWER","SOBHA","RATEGAIN","MFSL","GOCOLORS","IDEA","IDBI","AIAENG",
    "MAHABANK","LALPATHLAB","SPARC","JBCHEPHARM","COALINDIA","TANLA","CUMMINSIND",
    "TATASTEEL","RELIANCE","DALBHARAT","SBILIFE","FSL","PERSISTENT","BALRAMCHIN",
    "POONAWALLA","MOTHERSON","NBCC","COCHINSHIP","BPCL","NETWORK18","MEDPLUS",
    "JMFINANCIL","YESBANK","KEI","MAXHEALTH","BHARATFORG","BANDHANBNK","TITAN",
    "JINDALSTEL","HCLTECH","EIDPARRY","DELHIVERY","WHIRLPOOL","PNB","INDHOTEL",
    "SBICARD","INDUSINDBK","STAR","IOC","REDINGTON","DIVISLAB","SAIL","BIOCON",
    "JSL","DRREDDY","MAHLOG","TORNTPHARM","WELCORP","LT","TRITURBINE","MARUTI",
    "FEDERALBNK","ICICIPRULI","PHOENIXLTD","SFL","M&M","INGERRAND","DATAPATTNS",
    "BAJAJ-AUTO","NUVOCO","CHOLAFIN","NMDC","ULTRACEMCO","NYKAA","IDFCFIRSTB",
    "SUNPHARMA","TITAGARH","KOTAKBANK","LUPIN","APOLLOTYRE","ADANIPORTS","HUDCO",
    "APOLLOHOSP","DABUR","MAHLIFE","GRANULES","CGPOWER","BANKBARODA","HINDUNILVR",
    "CHALET","NATCOPHARM","HDFCLIFE","CANFINHOME","NESTLEIND","ASIANPAINT",
    "SAFARI","TRENT","HAL","ZYDUSLIFE","TORNTPOWER","MRF","AXISBANK","PAGEIND",
    "BHARTIARTL","TATACHEM","ICICIGI","TECHM","BRITANNIA","CIPLA","NTPC",
    "ADANIGREEN","ITC","JSWSTEEL","GAIL","TATACONSUM","INFY","BAJFINANCE",
    "WIPRO","ABB","GRASIM","POWERGRID","BAJAJFINSV","TCS","HDFCBANK","ICICIBANK",
    "PETRONET","MARICO","ONGC","ADANIENT","IRCTC",
]

# Per-stock best entry trigger (proven from backtest — do not change)
BEST_TRIGGER = {
    "NATIONALUM":"RSI_CROSS","SYRMA":"FORCE_IDX","LAURUSLABS":"BUY_STOP",
    "HINDCOPPER":"BUY_STOP","ABCAPITAL":"FORCE_IDX","MUTHOOTFIN":"RSI_CROSS",
    "CUB":"BUY_STOP","ASHOKLEY":"FORCE_IDX","HEROMOTOCO":"BUY_STOP",
    "RBLBANK":"FORCE_IDX","BOSCHLTD":"FORCE_IDX","DIXON":"RSI_CROSS",
    "FORTIS":"RSI_CROSS","IIFL":"BUY_STOP","BEL":"FORCE_IDX",
    "HINDALCO":"RSI_CROSS","BANKINDIA":"RSI_CROSS","THERMAX":"BUY_STOP",
    "UNIONBANK":"BUY_STOP","AUBANK":"BUY_STOP","VEDL":"FORCE_IDX",
    "BHEL":"RSI_CROSS","PAYTM":"BUY_STOP","INDIANB":"RSI_CROSS",
    "POLYCAB":"RSI_CROSS","UTIAMC":"FORCE_IDX","ADANIPOWER":"BUY_STOP",
    "DBREALTY":"RSI_CROSS","DCMSHRIRAM":"FORCE_IDX","TVSMOTOR":"FORCE_IDX",
    "SBIN":"FORCE_IDX","CDSL":"FORCE_IDX","KRBL":"RSI_CROSS",
    "ECLERX":"FORCE_IDX","VIPIND":"RSI_CROSS","COFORGE":"FORCE_IDX",
    "M&MFIN":"FORCE_IDX","EICHERMOT":"BUY_STOP","CRISIL":"FORCE_IDX",
    "RAMCOCEM":"FORCE_IDX","SUZLON":"FORCE_IDX","ZEEL":"FORCE_IDX",
    "NAVINFLUOR":"FORCE_IDX","CANBK":"RSI_CROSS","CHENNPETRO":"FORCE_IDX",
    "RADICO":"RSI_CROSS","ANGELONE":"BUY_STOP","ZENTEC":"BUY_STOP",
    "JIOFIN":"FORCE_IDX","PRESTIGE":"BUY_STOP","MINDSPACE":"BUY_STOP",
    "INDUSTOWER":"RSI_CROSS","SOBHA":"RSI_CROSS","RATEGAIN":"BUY_STOP",
    "MFSL":"BUY_STOP","GOCOLORS":"BUY_STOP","IDEA":"FORCE_IDX",
    "IDBI":"FORCE_IDX","AIAENG":"FORCE_IDX","MAHABANK":"FORCE_IDX",
    "LALPATHLAB":"RSI_CROSS","SPARC":"RSI_CROSS","JBCHEPHARM":"BUY_STOP",
    "COALINDIA":"FORCE_IDX","TANLA":"BUY_STOP","CUMMINSIND":"BUY_STOP",
    "TATASTEEL":"BUY_STOP","RELIANCE":"FORCE_IDX","DALBHARAT":"RSI_CROSS",
    "SBILIFE":"FORCE_IDX","FSL":"RSI_CROSS","PERSISTENT":"RSI_CROSS",
    "BALRAMCHIN":"RSI_CROSS","POONAWALLA":"FORCE_IDX","MOTHERSON":"FORCE_IDX",
    "NBCC":"BUY_STOP","COCHINSHIP":"BUY_STOP","BPCL":"BUY_STOP",
    "NETWORK18":"BUY_STOP","MEDPLUS":"BUY_STOP","JMFINANCIL":"FORCE_IDX",
    "YESBANK":"BUY_STOP","KEI":"BUY_STOP","MAXHEALTH":"BUY_STOP",
    "BHARATFORG":"FORCE_IDX","BANDHANBNK":"RSI_CROSS","TITAN":"RSI_CROSS",
    "JINDALSTEL":"RSI_CROSS","HCLTECH":"BUY_STOP","EIDPARRY":"RSI_CROSS",
    "DELHIVERY":"FORCE_IDX","WHIRLPOOL":"RSI_CROSS","PNB":"FORCE_IDX",
    "INDHOTEL":"BUY_STOP","SBICARD":"BUY_STOP","INDUSINDBK":"BUY_STOP",
    "STAR":"FORCE_IDX","IOC":"FORCE_IDX","REDINGTON":"RSI_CROSS",
    "DIVISLAB":"BUY_STOP","SAIL":"RSI_CROSS","BIOCON":"RSI_CROSS",
    "JSL":"FORCE_IDX","DRREDDY":"BUY_STOP","MAHLOG":"RSI_CROSS",
    "TORNTPHARM":"BUY_STOP","WELCORP":"FORCE_IDX","LT":"FORCE_IDX",
    "TRITURBINE":"BUY_STOP","MARUTI":"FORCE_IDX","FEDERALBNK":"RSI_CROSS",
    "ICICIPRULI":"BUY_STOP","PHOENIXLTD":"RSI_CROSS","SFL":"BUY_STOP",
    "M&M":"RSI_CROSS","INGERRAND":"RSI_CROSS","DATAPATTNS":"BUY_STOP",
    "BAJAJ-AUTO":"BUY_STOP","NUVOCO":"BUY_STOP","CHOLAFIN":"FORCE_IDX",
    "NMDC":"BUY_STOP","ULTRACEMCO":"FORCE_IDX","NYKAA":"RSI_CROSS",
    "IDFCFIRSTB":"FORCE_IDX","SUNPHARMA":"BUY_STOP","TITAGARH":"FORCE_IDX",
    "KOTAKBANK":"FORCE_IDX","LUPIN":"BUY_STOP","APOLLOTYRE":"FORCE_IDX",
    "ADANIPORTS":"BUY_STOP","HUDCO":"FORCE_IDX","APOLLOHOSP":"BUY_STOP",
    "DABUR":"RSI_CROSS","MAHLIFE":"RSI_CROSS","GRANULES":"FORCE_IDX",
    "CGPOWER":"RSI_CROSS","BANKBARODA":"RSI_CROSS","HINDUNILVR":"RSI_CROSS",
    "CHALET":"BUY_STOP","NATCOPHARM":"FORCE_IDX","HDFCLIFE":"FORCE_IDX",
    "CANFINHOME":"BUY_STOP","NESTLEIND":"FORCE_IDX","ASIANPAINT":"RSI_CROSS",
    "SAFARI":"RSI_CROSS","TRENT":"RSI_CROSS","HAL":"FORCE_IDX",
    "ZYDUSLIFE":"BUY_STOP","TORNTPOWER":"BUY_STOP","MRF":"FORCE_IDX",
    "AXISBANK":"RSI_CROSS","PAGEIND":"BUY_STOP","BHARTIARTL":"RSI_CROSS",
    "TATACHEM":"RSI_CROSS","ICICIGI":"FORCE_IDX","TECHM":"FORCE_IDX",
    "BRITANNIA":"BUY_STOP","CIPLA":"RSI_CROSS","NTPC":"BUY_STOP",
    "ADANIGREEN":"RSI_CROSS","ITC":"FORCE_IDX","JSWSTEEL":"BUY_STOP",
    "GAIL":"RSI_CROSS","TATACONSUM":"BUY_STOP","INFY":"FORCE_IDX",
    "BAJFINANCE":"FORCE_IDX","WIPRO":"BUY_STOP","ABB":"BUY_STOP",
    "GRASIM":"BUY_STOP","POWERGRID":"RSI_CROSS","BAJAJFINSV":"RSI_CROSS",
    "TCS":"RSI_CROSS","HDFCBANK":"RSI_CROSS","ICICIBANK":"BUY_STOP",
    "PETRONET":"BUY_STOP","MARICO":"BUY_STOP","ONGC":"BUY_STOP",
    "ADANIENT":"RSI_CROSS","IRCTC":"RSI_CROSS",
}


# ============================================================================
# INDICATORS  — exact match to live_trading_bot_final.py
# ============================================================================
def _ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def _rsi(s: pd.Series, p: int = 14) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(span=p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=p, adjust=False).mean()
    return 100 - 100 / (1 + g / (l + 1e-10))

def _fi(close: pd.Series, vol: pd.Series, p: int = 13) -> pd.Series:
    return (close.diff() * vol).ewm(span=p, adjust=False).mean()

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, p: int = 14) -> pd.Series:
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def compute_signals(df: pd.DataFrame, use_per_stock_trigger: bool = True) -> pd.DataFrame:
    """
    Adds signal columns to daily OHLCV dataframe.
    Exact match to check_signals() in live_trading_bot_final.py.

    Screen 1: close > EMA(50)           — weekly trend filter
    Screen 2: RSI(2) < 30 [yesterday]   — daily pullback (shift 1 to avoid lookahead)
    Screen 3: per-stock trigger          — entry confirmation
    """
    df = df.copy()
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

    df["ema50"]   = _ema(close, 50)
    df["rsi2"]    = _rsi(close, 2)
    df["rsi14"]   = _rsi(close, 14)
    df["fi13"]    = _fi(close, vol, 13)
    df["atr14"]   = _atr(high, low, close, 14)

    # Screens
    df["s1"]      = close > df["ema50"]
    df["s2"]      = df["rsi2"].shift(1) < 30   # yesterday pullback — no lookahead

    # Screen 3 signals — computed for all three trigger types
    df["bs_sig"]  = close > high.shift(1)                      # BUY_STOP
    df["rc_sig"]  = (df["rsi14"] > 40) & (df["rsi14"].shift(1) <= 40)  # RSI_CROSS
    df["fi_sig"]  = (df["fi13"] > 0) & (df["fi13"].shift(1) <= 0)     # FORCE_IDX

    df["atr"]     = df["atr14"]
    return df


# ============================================================================
# DATA DOWNLOAD
# ============================================================================
def download_stock(sym: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        df = yf.download(f"{sym}.NS", start=start, end=end,
                         auto_adjust=True, progress=False)
        if df is None or df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open","High","Low","Close","Volume"]].dropna()
        return df
    except Exception:
        return None


# ============================================================================
# BACKTEST ENGINE
# ============================================================================
def run_backtest(stocks: list[str], cfg: dict,
                 use_per_stock_trigger: bool = True) -> tuple[pd.DataFrame, pd.Series]:
    start  = cfg["START"]
    end    = cfg["END"] or dt.date.today().isoformat()
    cap    = cfg["CAPITAL"]

    # Download Nifty for regime filter
    try:
        nf = yf.download("^NSEI", start=start, end=end,
                         auto_adjust=True, progress=False)
        if isinstance(nf.columns, pd.MultiIndex):
            nf.columns = nf.columns.get_level_values(0)
        nifty_bull = (nf["Close"] > nf["Close"].rolling(200).mean()).reindex(
            pd.bdate_range(start, end)).ffill().fillna(True)
    except Exception:
        nifty_bull = pd.Series(True, index=pd.bdate_range(start, end))

    # Download and compute signals for all stocks
    print(f"  Downloading {len(stocks)} stocks...")
    stock_data: dict[str, pd.DataFrame] = {}
    failed = 0
    for i, sym in enumerate(stocks):
        df = download_stock(sym, start, end)
        if df is None:
            failed += 1
            continue
        stock_data[sym] = compute_signals(df, use_per_stock_trigger)
        if (i+1) % 30 == 0:
            print(f"  {i+1}/{len(stocks)} downloaded ({len(stock_data)} ok, {failed} skipped)")
    print(f"  {len(stock_data)} stocks ready ({failed} skipped)")

    if not stock_data:
        return pd.DataFrame(), pd.Series(dtype=float)

    all_dates = sorted(set(d for df in stock_data.values() for d in df.index))
    all_dates = [d for d in all_dates if d >= pd.Timestamp(start)]

    cash      = cap
    positions: dict[str, dict] = {}
    equity: list[tuple]        = []
    trades:  list[dict]        = []

    # Track per-stock entry dates to prevent same-day re-entry
    last_entry: dict[str, pd.Timestamp] = {}

    for d in all_dates:
        # 1. Check stop losses on existing positions
        to_exit = []
        for sym, pos in positions.items():
            df = stock_data.get(sym)
            if df is None or d not in df.index:
                continue
            row = df.loc[d]
            lo  = float(row["Low"])
            if lo <= pos["stop"]:
                exit_px = min(float(row["Open"]), pos["stop"])
                to_exit.append((sym, exit_px, "STOP"))
            # Optional: also exit on RSI(2) > 95 (overbought)
            rsi2 = float(row["rsi2"]) if "rsi2" in row.index and not pd.isna(row["rsi2"]) else 50
            if rsi2 > 95:
                to_exit.append((sym, float(row["Close"]), "RSI_OVERBOUGHT"))

        for sym, exit_px, reason in to_exit:
            if sym not in positions:
                continue
            pos    = positions.pop(sym)
            pnl    = (exit_px - pos["entry_px"]) * pos["qty"]
            pnl_pct= (exit_px - pos["entry_px"]) / pos["entry_px"] * 100
            cash  += exit_px * pos["qty"]
            held   = (d - pos["entry_date"]).days
            trades.append(dict(
                date=d.date().isoformat(), symbol=sym, action="SELL",
                qty=pos["qty"], price=round(exit_px, 2),
                entry_px=round(pos["entry_px"], 2),
                pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
                held_days=held, trigger=pos["trigger"],
                reason=reason, model="TripleScreen",
            ))

        # 2. Scan for new entries
        bull = bool(nifty_bull.get(d, True))
        new_today = 0
        if bull and len(positions) < cfg["MAX_POS"]:
            candidates = []
            for sym in stocks:
                if sym in positions:
                    continue
                if sym in {t[0] for t in to_exit}:
                    continue
                df = stock_data.get(sym)
                if df is None or d not in df.index:
                    continue
                row = df.loc[d]

                # All three screens
                s1 = bool(row.get("s1", False))
                s2 = bool(row.get("s2", False))

                # Screen 3: use per-stock trigger or combine all
                if use_per_stock_trigger:
                    t = BEST_TRIGGER.get(sym, "BUY_STOP")
                    if t == "BUY_STOP":
                        s3 = bool(row.get("bs_sig", False))
                    elif t == "RSI_CROSS":
                        s3 = bool(row.get("rc_sig", False))
                    else:
                        s3 = bool(row.get("fi_sig", False))
                else:
                    # Compare mode: any trigger fires
                    s3 = bool(row.get("bs_sig", False) or
                               row.get("rc_sig", False) or
                               row.get("fi_sig", False))
                    t  = "ANY"

                if not (s1 and s2 and s3):
                    continue

                price = float(row["Close"])
                if price < cfg["MIN_PRICE"]:
                    continue

                atr = float(row["atr"]) if not pd.isna(row["atr"]) else price * 0.02
                if atr <= 0:
                    atr = price * 0.02

                stop = round(price - cfg["ATR_MULT"] * atr, 2)
                risk_per_share = price - stop
                if risk_per_share <= 0:
                    continue

                qty = int((cash * cfg["RISK_PCT"]) / risk_per_share)
                qty = min(qty, int(cash * 0.20 / price))  # max 20% per stock
                if qty < 1:
                    continue

                candidates.append((sym, price, atr, stop, qty, t))

            # Take up to MAX_NEW_DAY candidates ranked by largest pullback (RSI2 lowest)
            def rsi2_val(sym):
                df = stock_data.get(sym)
                if df is None or d not in df.index:
                    return 100
                return float(df.loc[d, "rsi2"]) if "rsi2" in df.columns else 100

            candidates.sort(key=lambda x: rsi2_val(x[0]))

            for sym, price, atr, stop, qty, trigger in candidates:
                if new_today >= cfg["MAX_NEW_DAY"]:
                    break
                if len(positions) >= cfg["MAX_POS"]:
                    break
                cost = price * qty
                if cost > cash:
                    continue
                cash -= cost
                positions[sym] = dict(
                    entry_px=price, qty=qty, stop=stop,
                    entry_date=d, trigger=trigger, atr=atr,
                )
                trades.append(dict(
                    date=d.date().isoformat(), symbol=sym, action="BUY",
                    qty=qty, price=round(price, 2),
                    entry_px=round(price, 2),
                    pnl=0.0, pnl_pct=0.0, held_days=0,
                    trigger=trigger, reason="SIGNAL", model="TripleScreen",
                ))
                new_today += 1

        # 3. Mark-to-market equity
        mtm = cash
        for sym, pos in positions.items():
            df = stock_data.get(sym)
            if df is not None and d in df.index:
                mtm += float(df.loc[d, "Close"]) * pos["qty"]
            else:
                mtm += pos["entry_px"] * pos["qty"]
        equity.append((d, mtm))

    # Close remaining positions at end
    last_date = pd.Timestamp(end)
    for sym, pos in list(positions.items()):
        df = stock_data.get(sym)
        if df is not None and not df.empty:
            avail  = df[df.index <= last_date]
            exit_px = float(avail.iloc[-1]["Close"]) if not avail.empty else pos["entry_px"]
            exit_dt = avail.index[-1] if not avail.empty else last_date
        else:
            exit_px, exit_dt = pos["entry_px"], last_date
        cash  += exit_px * pos["qty"]
        pnl    = (exit_px - pos["entry_px"]) * pos["qty"]
        pnl_pct= (exit_px - pos["entry_px"]) / pos["entry_px"] * 100
        held   = (exit_dt - pos["entry_date"]).days
        trades.append(dict(
            date=exit_dt.date().isoformat(), symbol=sym, action="SELL",
            qty=pos["qty"], price=round(exit_px, 2),
            entry_px=round(pos["entry_px"], 2),
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            held_days=held, trigger=pos["trigger"],
            reason="EOD_CLOSE", model="TripleScreen",
        ))

    trades_df = pd.DataFrame(trades)
    eq_series = pd.Series(dict(equity)).sort_index()
    return trades_df, eq_series


# ============================================================================
# METRICS
# ============================================================================
def calc_metrics(trades: pd.DataFrame, eq: pd.Series, cfg: dict) -> dict:
    if eq.empty:
        return {}
    yrs    = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr   = (eq.iloc[-1] / cfg["CAPITAL"]) ** (1 / yrs) - 1
    rets   = eq.pct_change().dropna()
    rf     = 0.065 / 252
    excess = rets - rf
    std    = excess.std()
    sharpe = float(np.sqrt(252) * excess.mean() / std) if std > 0 else 0
    dstd   = rets[rets < 0].std()
    sortino= float(np.sqrt(252) * excess.mean() / dstd) if dstd > 0 else 0
    peaks  = eq.cummax()
    max_dd = float(((eq - peaks) / peaks).min() * 100)
    sells  = trades[trades["action"] == "SELL"]
    n      = len(sells)
    wr     = float((sells["pnl"] > 0).mean() * 100) if n > 0 else 0
    avg_w  = float(sells[sells["pnl"] > 0]["pnl_pct"].mean()) if (sells["pnl"] > 0).any() else 0
    avg_l  = float(sells[sells["pnl"] < 0]["pnl_pct"].mean()) if (sells["pnl"] < 0).any() else 0
    pf     = abs(avg_w / avg_l) if avg_l != 0 else 0
    hold   = float(sells["held_days"].mean()) if n > 0 else 0
    return dict(cagr=cagr*100, sharpe=sharpe, sortino=sortino, max_dd=max_dd,
                wr=wr, avg_win=avg_w, avg_loss=avg_l, pf=pf, n=n,
                avg_hold=hold, final=eq.iloc[-1])


# ============================================================================
# REPORT  — standard format matching NSE200 and HM
# ============================================================================
def report(trades: pd.DataFrame, eq: pd.Series, cfg: dict,
           index_cagr: float, verbose: bool = True):
    if eq.empty:
        print("  No equity data — check your stock list or date range")
        return
    m      = calc_metrics(trades, eq, cfg)
    start  = cfg["START"]
    end    = cfg["END"] or dt.date.today().isoformat()
    yrs    = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25

    print("\n" + "=" * 70)
    print(f"TRIPLE SCREEN DEFENSE  risk={cfg['RISK_PCT']*100:.0f}%  "
          f"atr_mult={cfg['ATR_MULT']}  max_pos={cfg['MAX_POS']}")
    print("=" * 70)
    print(f"Period       : {start} → {end} ({yrs:.1f}y)")
    print(f"Final equity : Rs  {m['final']:>12,.0f}  "
          f"(start Rs {cfg['CAPITAL']:,.0f})")
    print(f"Total return : {(m['final']/cfg['CAPITAL']-1)*100:>8.2f}%")
    print(f"CAGR         : {m['cagr']:>8.2f}%")
    print(f"Sharpe       : {m['sharpe']:>8.2f}")
    print(f"Sortino      : {m['sortino']:>8.2f}")
    print(f"Max drawdown : {m['max_dd']:>8.2f}%")
    print(f"Index CAGR   : {index_cagr:>8.2f}%    alpha {m['cagr']-index_cagr:+.2f}%")
    print("-" * 70)
    print(f"Trades       : {m['n']}")
    print(f"Win rate     : {m['wr']:>8.2f}%")
    print(f"Avg win      : {m['avg_win']:>+8.2f}%    Avg loss : {m['avg_loss']:>+.2f}%")
    print(f"Profit factor: {m['pf']:>8.2f}")
    print(f"Avg hold     : {m['avg_hold']:>5.0f} days")

    if not verbose:
        print("=" * 70)
        return

    # Trigger breakdown
    sells = trades[trades["action"] == "SELL"]
    if not sells.empty and "trigger" in sells.columns:
        print("\nPer-trigger breakdown:")
        print(f"  {'Trigger':<12} {'Trades':>6} {'WR%':>6} {'AvgRet%':>8}")
        for trig in ["BUY_STOP","RSI_CROSS","FORCE_IDX","ANY"]:
            sub = sells[sells["trigger"] == trig]
            if sub.empty:
                continue
            tw  = (sub["pnl"] > 0).mean() * 100
            ta  = sub["pnl_pct"].mean()
            print(f"  {trig:<12} {len(sub):>6} {tw:>6.1f} {ta:>+8.2f}%")

    # Per-symbol P&L — top 20 and bottom 10
    if not sells.empty:
        sym_pnl = (sells.groupby("symbol")
                   .agg(trades=("pnl","count"),
                        net_pnl=("pnl","sum"),
                        wr=("pnl", lambda x: 100*(x>0).mean()),
                        avg_ret=("pnl_pct","mean"),
                        avg_hold=("held_days","mean"))
                   .sort_values("net_pnl", ascending=False))

        print("\nPer-symbol P&L  (top 20 and bottom 10)")
        print("-" * 70)
        print(f"{'Symbol':<16} {'Trades':>6} {'Net P&L':>12} {'WR%':>6} "
              f"{'AvgRet%':>8} {'AvgHold':>8}")
        for sym, row in sym_pnl.head(20).iterrows():
            print(f"{sym:<16} {int(row.trades):>6} {row.net_pnl:>12,.0f} "
                  f"{row.wr:>6.1f} {row.avg_ret:>+8.2f}% {row.avg_hold:>7.0f}d")
        if len(sym_pnl) > 20:
            print("  ...")
            for sym, row in sym_pnl.tail(10).iterrows():
                flag = " ◄ DRAG" if row.net_pnl < 0 else ""
                print(f"{sym:<16} {int(row.trades):>6} {row.net_pnl:>12,.0f} "
                      f"{row.wr:>6.1f} {row.avg_ret:>+8.2f}% "
                      f"{row.avg_hold:>7.0f}d{flag}")

    print("=" * 70)


# ============================================================================
# SWEEP — compare trigger modes
# ============================================================================
def run_sweep(stocks: list[str], cfg: dict, index_cagr: float):
    modes = [
        ("per_stock_trigger", True),
        ("any_trigger",       False),
    ]
    results = []
    for label, use_per in modes:
        print(f"  sweep: {label}...", end="\r")
        t, eq = run_backtest(stocks, cfg, use_per_stock_trigger=use_per)
        if eq.empty:
            continue
        m = calc_metrics(t, eq, cfg)
        results.append(dict(mode=label, **m))

    print("\n" + "=" * 70)
    print("TRIPLE SCREEN SWEEP — trigger modes")
    print("=" * 70)
    print(f"{'Mode':<22} {'CAGR%':>7} {'Sharpe':>7} {'MaxDD%':>8} {'WR%':>6} {'Trades':>7}")
    print("-" * 70)
    for r in results:
        print(f"{r['mode']:<22} {r['cagr']:>7.2f} {r['sharpe']:>7.2f} "
              f"{r['max_dd']:>8.2f} {r['wr']:>6.1f} {int(r['n']):>7}")
    print("=" * 70)


# ============================================================================
# NIFTY INDEX CAGR
# ============================================================================
def nifty_cagr(start: str, end: str) -> float:
    try:
        nf = yf.download("^NSEI", start=start, end=end,
                         progress=False, auto_adjust=True)
        if nf.empty:
            return 0.0
        if isinstance(nf.columns, pd.MultiIndex):
            nf.columns = nf.columns.get_level_values(0)
        c   = nf["Close"].dropna()
        yrs = (c.index[-1] - c.index[0]).days / 365.25
        return ((float(c.iloc[-1]) / float(c.iloc[0])) ** (1/yrs) - 1) * 100
    except Exception:
        return 0.0


# ============================================================================
# MAIN
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="Triple Screen Defense Backtest")
    ap.add_argument("--start",      type=str,   default=None,
                    help="Start date YYYY-MM-DD (default: 2018-01-01)")
    ap.add_argument("--capital",    type=float, default=None,
                    help="Starting capital Rs (default: 100000)")
    ap.add_argument("--stocks",     nargs="+",  default=None,
                    help="Focused backtest on specific stocks, e.g. --stocks CGPOWER IIFL")
    ap.add_argument("--sweep",      action="store_true",
                    help="Compare per-stock triggers vs any-trigger mode")
    ap.add_argument("--notrigger",  action="store_true",
                    help="Ignore per-stock triggers — use any Screen 3 signal")
    args = ap.parse_args()

    cfg = dict(CFG)
    if args.start:    cfg["START"]   = args.start
    if args.capital:  cfg["CAPITAL"] = args.capital

    end = cfg["END"] or dt.date.today().isoformat()
    use_per = not args.notrigger

    if args.stocks:
        stocks = [s.upper() for s in args.stocks]
        print(f"[stocks] focused: {stocks}")
    else:
        stocks = list(STOCKS)

    print("=" * 70)
    print("TRIPLE SCREEN DEFENSE BACKTEST")
    print(f"Period: {cfg['START']} → {end}  |  "
          f"Capital: Rs {cfg['CAPITAL']:,.0f}  |  "
          f"Universe: {len(stocks)} stocks")
    print(f"Triggers: {'per-stock (best)' if use_per else 'any trigger'}")
    print("=" * 70)

    idx_cagr = nifty_cagr(cfg["START"], end)

    if args.sweep:
        run_sweep(stocks, cfg, idx_cagr)
        return

    trades, eq = run_backtest(stocks, cfg, use_per_stock_trigger=use_per)

    if trades.empty:
        print("  No trades generated — check date range or stock list")
        sys.exit(0)

    report(trades, eq, cfg, idx_cagr, verbose=True)

    # Save standard trade CSV
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(script_dir, cfg["TRADE_CSV"])
    trades.to_csv(out, index=False)
    print(f"\nTrade log → {out}")


if __name__ == "__main__":
    main()
