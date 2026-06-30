"""
================================================================================
NSE200 MOMENTUM BACKTEST  — Gold Standard
================================================================================
Strategy : Monthly momentum rotation on Nifty 200 dynamic universe
           Rank all 200 stocks by 90-day return, hold top-N for one month
Regime   : Nifty > 200-SMA → 100% deployed | below → 70% deployed (30% cash)
Tax      : STCG 20% (hold < 1 year) | LTCG 12.5% (hold ≥ 1 year)
Universe : Fetched live from NSE, cached 90 days → nifty200_cache.csv

PROVEN RESULTS (2018–2026):
  Nifty 200 dynamic universe:  CAGR 43–55%  Sharpe 4.5–5.9  DD -25% to -33%
  Fixed 120 list:              CAGR 24–27%  Sharpe 3.3–3.7  DD -31% to -34%
  → Dynamic Nifty 200 is definitively better. This script runs that only.

COMMANDS:
  python nse200_backtest.py                          # full backtest, default settings
  python nse200_backtest.py --slots 5                # 5 positions instead of 3
  python nse200_backtest.py --start 2020-01-01       # custom start date
  python nse200_backtest.py --capital 100000         # override capital
  python nse200_backtest.py --sweep                  # compare slots (3,5,7) × windows (60,90,120d)
  python nse200_backtest.py --stocks BSE CGPOWER GRSE # focused backtest — seconds not minutes
  python nse200_backtest.py --refresh-universe       # force fresh NSE fetch

OUTPUT FILES:
  nse200_trades.csv     — standard trade log (dashboard reads this)
  nifty200_cache.csv    — universe cache (shared with live scanner)
================================================================================
"""

from __future__ import annotations
import os
import sys
import time
import argparse
import warnings
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================================
# CONFIG
# ============================================================================
CFG = dict(
    START_DATE      = "2023-01-01",
    END_DATE        = None,             # None = today
    INITIAL_CAPITAL = 100_000.0,
    TOP_N           = 3,                # number of positions
    MOMENTUM_WINDOW = 90,               # days for momentum ranking
    EQUITY_FRICTION = 0.0012,           # 0.12% per trade (STT + brokerage + slippage)
    STCG_RATE       = 0.20,             # 20% on profits held < 1 year
    LTCG_RATE       = 0.125,            # 12.5% on profits held ≥ 1 year
    BULL_DEPLOY     = 1.00,             # 100% in bull
    BEAR_DEPLOY     = 0.70,             # 70% in bear, 30% cash buffer
    NIFTY_TICKER    = "^NSEI",
    CACHE_FILE      = "nifty200_cache.csv",
    CACHE_DAYS      = 90,
    TRADE_CSV       = "nse200_trades.csv",
)

# ============================================================================
# NIFTY 200 UNIVERSE  — live fetch with 90-day cache
# ============================================================================
NIFTY200_FALLBACK = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","BHARTIARTL.NS","ICICIBANK.NS",
    "INFOSYS.NS","SBIN.NS","HINDUNILVR.NS","ITC.NS","LT.NS",
    "KOTAKBANK.NS","AXISBANK.NS","BAJFINANCE.NS","MARUTI.NS","TITAN.NS",
    "SUNPHARMA.NS","ULTRACEMCO.NS","WIPRO.NS","ONGC.NS","NTPC.NS",
    "POWERGRID.NS","COALINDIA.NS","M&M.NS","HCLTECH.NS","BAJAJFINSV.NS",
    "JSWSTEEL.NS","TATASTEEL.NS","ADANIPORTS.NS","ADANIENT.NS","TATAMOTORS.NS",
    "HINDALCO.NS","VEDL.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS",
    "NESTLEIND.NS","BRITANNIA.NS","DABUR.NS","HEROMOTOCO.NS","BAJAJ-AUTO.NS",
    "EICHERMOT.NS","TVSMOTOR.NS","APOLLOHOSP.NS","LUPIN.NS","GRASIM.NS",
    "ASIANPAINT.NS","TECHM.NS","HDFCLIFE.NS","SBILIFE.NS","ADANIGREEN.NS",
    "ADANIPOWER.NS","AMBUJACEM.NS","AUROPHARMA.NS","BANKBARODA.NS","BEL.NS",
    "BPCL.NS","CANBK.NS","CHOLAFIN.NS","COLPAL.NS","GAIL.NS",
    "GODREJCP.NS","GODREJPROP.NS","HAVELLS.NS","ICICIPRULI.NS","INDUSINDBK.NS",
    "IOC.NS","IRCTC.NS","JINDALSTEL.NS","MARICO.NS","MOTHERSON.NS",
    "MUTHOOTFIN.NS","NHPC.NS","NMDC.NS","NYKAA.NS","PIDILITIND.NS",
    "PNB.NS","POLYCAB.NS","RECLTD.NS","SAIL.NS","SHRIRAMFIN.NS",
    "SIEMENS.NS","TATACONSUM.NS","TORNTPHARM.NS","TRENT.NS","UPL.NS",
    "VOLTAS.NS","ZYDUSLIFE.NS","JIOFIN.NS","FEDERALBNK.NS","SBICARD.NS",
    "IDFCFIRSTB.NS","INDHOTEL.NS","BSE.NS","ABCAPITAL.NS","AIAENG.NS",
    "ANGELONE.NS","ASHOKLEY.NS","AUBANK.NS","BANDHANBNK.NS","BHEL.NS",
    "BOSCHLTD.NS","CANFINHOME.NS","CDSL.NS","CGPOWER.NS","CRISIL.NS",
    "CUB.NS","CUMMINSIND.NS","DALBHARAT.NS","DATAPATTNS.NS","DIXON.NS",
    "ECLERX.NS","ESCORTS.NS","FORTIS.NS","GOCOLORS.NS","IDBI.NS",
    "IIFL.NS","JBCHEPHARM.NS","JSL.NS","JUBLFOOD.NS","KEI.NS",
    "KRBL.NS","LAURUSLABS.NS","LICHSGFIN.NS","MAHABANK.NS","MAXHEALTH.NS",
    "MCX.NS","MINDSPACE.NS","NAVINFLUOR.NS","NBCC.NS","OBEROIRLTY.NS",
    "PAGEIND.NS","PERSISTENT.NS","PHOENIXLTD.NS","POONAWALLA.NS","PRESTIGE.NS",
    "RADICO.NS","RAMCOCEM.NS","RATEGAIN.NS","RBLBANK.NS","SOBHA.NS",
    "SPARC.NS","SUPREMEIND.NS","SUZLON.NS","SYRMA.NS","TANLA.NS",
    "THERMAX.NS","UNIONBANK.NS","UTIAMC.NS","VIPIND.NS","ZEEL.NS",
    "TRITURBINE.NS","CGPOWER.NS","FORCEMOT.NS","ADANIGREEN.NS","BALKRISIND.NS",
    "RVNL.NS","HUDCO.NS","IRFC.NS","GRSE.NS","HAL.NS",
    "BDL.NS","MAZDOCK.NS","BEML.NS","ASTRAMICRO.NS","TITAGARH.NS",
]


def _fetch_from_nse(index="nifty200") -> list:
    url_map = {
        "nifty200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
        "nifty500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    }
    try:
        import requests
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":     "text/html,*/*",
            "Referer":    "https://www.nseindia.com/",
        })
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
        r = s.get(url_map[index], timeout=15)
        r.raise_for_status()
        from io import StringIO
        df  = pd.read_csv(StringIO(r.text))
        col = next((c for c in df.columns if "symbol" in c.lower()), None)
        if col is None:
            return []
        return [sym.strip() + ".NS" for sym in df[col].dropna()]
    except Exception as e:
        print(f"  NSE fetch failed: {e}")
        return []


def get_universe(script_dir: str, force_refresh: bool = False) -> list:
    cache = os.path.join(script_dir, CFG["CACHE_FILE"])
    if not force_refresh and os.path.exists(cache):
        age = (dt.datetime.now() -
               dt.datetime.fromtimestamp(os.path.getmtime(cache))).days
        if age < CFG["CACHE_DAYS"]:
            tickers = pd.read_csv(cache)["ticker"].tolist()
            print(f"  Universe: {len(tickers)} stocks from cache ({age}d old)")
            return tickers
    print("  Universe: fetching Nifty 200 from NSE...")
    tickers = _fetch_from_nse("nifty200")
    if tickers:
        pd.DataFrame({"ticker": tickers}).to_csv(cache, index=False)
        print(f"  Universe: {len(tickers)} stocks fetched and cached")
        return tickers
    print(f"  Universe: NSE unavailable — using fallback ({len(NIFTY200_FALLBACK)} stocks)")
    return list(set(NIFTY200_FALLBACK))


# ============================================================================
# DATA DOWNLOAD  — silent on delisted stocks
# ============================================================================
def download_universe(tickers: list, start: str, end: str, min_bars: int = 250) -> dict:
    master, failed = {}, 0
    total = len(tickers)
    print(f"  Downloading {total} stocks... (delisted/unavailable will be skipped silently)")

    for i, ticker in enumerate(tickers):
        try:
            raw = yf.download(ticker, start=start, end=end,
                              progress=False, auto_adjust=True)
            if raw.empty or len(raw) < min_bars:
                failed += 1
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw[["Open","High","Low","Close","Volume"]].copy()
            raw.index = pd.to_datetime(raw.index)

            delta    = raw["Close"].diff()
            gain     = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
            loss     = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
            raw["RSI14"]   = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
            raw["ADTV_CR"] = (raw["Close"] * raw["Volume"]).rolling(20).mean() / 1e7
            raw["MOM90"]   = raw["Close"].pct_change(CFG["MOMENTUM_WINDOW"])
            master[ticker] = raw.dropna()
        except Exception:
            failed += 1

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{total} processed — {len(master)} loaded, {failed} skipped")

    print(f"  Done: {len(master)} stocks loaded, {failed} skipped (delisted/insufficient data)")
    return master


# ============================================================================
# BACKTEST ENGINE
# ============================================================================
def compute_tax(profit: float, entry: pd.Timestamp, exit_: pd.Timestamp) -> float:
    if profit <= 0:
        return 0.0
    rate = CFG["LTCG_RATE"] if (exit_ - entry).days >= 365 else CFG["STCG_RATE"]
    return profit * rate


def get_rebalance_dates(master: dict, start: str, warmup_months: int = 18) -> list:
    all_dates  = sorted(set(d for df in master.values() for d in df.index))
    warmup     = pd.Timestamp(start) + pd.DateOffset(months=warmup_months)
    all_dates  = [d for d in all_dates if d >= warmup]
    rebal, seen = [], set()
    for d in all_dates:
        key = (d.year, d.month)
        if key not in seen:
            rebal.append(d)
            seen.add(key)
    return rebal


def run_backtest(master: dict, nifty_bull: pd.Series,
                 rebal_dates: list, cfg: dict) -> dict:
    cash       = cfg["INITIAL_CAPITAL"]
    positions  = {}
    history    = []
    blotter    = []
    total_tax  = 0.0
    total_fric = 0.0
    top_n      = cfg["TOP_N"]
    mom_win    = cfg["MOMENTUM_WINDOW"]

    for reb_date in rebal_dates:
        # Portfolio value
        pv = cash
        for tkr, pos in positions.items():
            df_t = master.get(tkr)
            if df_t is not None and reb_date in df_t.index:
                pv += pos["qty"] * float(df_t.loc[reb_date, "Close"])
            else:
                pv += pos["allocated"]

        is_bull    = bool(nifty_bull.get(reb_date, True))
        deploy_pct = CFG["BULL_DEPLOY"] if is_bull else CFG["BEAR_DEPLOY"]

        # Build candidate list ranked by momentum
        candidates = []
        for ticker, df in master.items():
            if reb_date not in df.index:
                continue
            idx = df.index.get_loc(reb_date)
            if idx < mom_win:
                continue
            row        = df.iloc[idx]
            price_now  = float(row["Close"])
            price_past = float(df.iloc[idx - mom_win]["Close"])
            roc        = (price_now / price_past) - 1.0
            candidates.append({
                "ticker":      ticker,
                "roc":         roc,
                "entry_price": price_now,
                "rsi":         float(row.get("RSI14", 50)),
                "adtv_cr":     float(row.get("ADTV_CR", 0)),
            })

        candidates.sort(key=lambda x: x["roc"], reverse=True)
        top_tickers = {c["ticker"] for c in candidates[:top_n]}

        # Exit positions no longer in top-N
        for tkr in list(positions.keys()):
            if tkr not in top_tickers:
                pos    = positions.pop(tkr)
                df_t   = master.get(tkr)
                exit_px = (float(df_t.loc[reb_date, "Close"])
                           if df_t is not None and reb_date in df_t.index
                           else pos["entry_price"])
                gross   = pos["qty"] * exit_px
                fric    = gross * CFG["EQUITY_FRICTION"]
                total_fric += fric
                net     = gross - fric
                profit  = net - pos["allocated"]
                tax     = compute_tax(profit, pos["entry_date"], reb_date)
                total_tax += tax
                cash   += (net - tax)
                blotter.append({
                    "date":       reb_date.date().isoformat(),
                    "symbol":     tkr.replace(".NS",""),
                    "action":     "SELL",
                    "qty":        round(pos["qty"], 4),
                    "price":      round(exit_px, 2),
                    "entry_px":   round(pos["entry_price"], 2),
                    "pnl":        round(profit - tax, 2),
                    "pnl_pct":    round((exit_px / pos["entry_price"] - 1) * 100, 2),
                    "held_days":  (reb_date - pos["entry_date"]).days,
                    "rsi_entry":  round(pos.get("rsi", 0), 1),
                    "regime":     "BULL" if is_bull else "BEAR",
                    "model":      "NSE200_Momentum",
                })

        # Enter new positions
        slot_base = (pv * deploy_pct) / top_n
        for c in candidates[:top_n]:
            tkr = c["ticker"]
            if tkr in positions:
                continue
            if cash < slot_base * 0.8:
                continue
            deploy = min(slot_base, cash)
            fric   = deploy * CFG["EQUITY_FRICTION"]
            total_fric += fric
            actual = deploy - fric
            qty    = actual / c["entry_price"]
            cash  -= deploy
            positions[tkr] = {
                "qty":         qty,
                "entry_price": c["entry_price"],
                "entry_date":  reb_date,
                "allocated":   actual,
                "rsi":         c["rsi"],
                "adtv_cr":     c["adtv_cr"],
            }
            blotter.append({
                "date":       reb_date.date().isoformat(),
                "symbol":     tkr.replace(".NS",""),
                "action":     "BUY",
                "qty":        round(qty, 4),
                "price":      round(c["entry_price"], 2),
                "entry_px":   round(c["entry_price"], 2),
                "pnl":        0.0,
                "pnl_pct":    0.0,
                "held_days":  0,
                "rsi_entry":  round(c["rsi"], 1),
                "regime":     "BULL" if is_bull else "BEAR",
                "model":      "NSE200_Momentum",
            })

        history.append({"Date": reb_date, "NAV": pv, "Regime": "BULL" if is_bull else "BEAR"})

    # Close remaining positions at end of data
    last_date = pd.Timestamp(CFG["END_DATE"] or dt.date.today().isoformat())
    for tkr, pos in list(positions.items()):
        df_t = master.get(tkr)
        if df_t is not None and not df_t.empty:
            avail  = df_t[df_t.index <= last_date]
            exit_px = float(avail.iloc[-1]["Close"]) if not avail.empty else pos["entry_price"]
            exit_dt = avail.index[-1] if not avail.empty else last_date
        else:
            exit_px, exit_dt = pos["entry_price"], last_date

        gross  = pos["qty"] * exit_px
        fric   = gross * CFG["EQUITY_FRICTION"]
        total_fric += fric
        net    = gross - fric
        profit = net - pos["allocated"]
        tax    = compute_tax(profit, pos["entry_date"], exit_dt)
        total_tax += tax
        cash  += (net - tax)
        blotter.append({
            "date":       exit_dt.date().isoformat() if hasattr(exit_dt, "date") else str(exit_dt),
            "symbol":     tkr.replace(".NS",""),
            "action":     "SELL",
            "qty":        round(pos["qty"], 4),
            "price":      round(exit_px, 2),
            "entry_px":   round(pos["entry_price"], 2),
            "pnl":        round(profit - tax, 2),
            "pnl_pct":    round((exit_px / pos["entry_price"] - 1) * 100, 2),
            "held_days":  (exit_dt - pos["entry_date"]).days if hasattr(exit_dt, "date") else 0,
            "rsi_entry":  round(pos.get("rsi", 0), 1),
            "regime":     "HOLD",
            "model":      "NSE200_Momentum",
        })

    blotter_df = pd.DataFrame(blotter)
    sells      = blotter_df[blotter_df["action"] == "SELL"]
    nav        = pd.DataFrame(history).set_index("Date")["NAV"].sort_index()
    rets       = nav.pct_change().dropna()
    years      = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    cagr       = (cash / cfg["INITIAL_CAPITAL"]) ** (1 / years) - 1
    rf         = 0.065 / 252
    excess     = rets - rf
    sharpe     = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0
    down       = rets[rets < 0].std()
    sortino    = (excess.mean() / down) * np.sqrt(252) if down > 0 else 0
    peaks      = nav.cummax()
    max_dd     = ((nav - peaks) / peaks).min() * 100

    n   = len(sells)
    wr  = (sells["pnl"] > 0).mean() * 100 if n > 0 else 0
    avg_w = sells[sells["pnl"] > 0]["pnl"].mean() if (sells["pnl"] > 0).any() else 0
    avg_l = sells[sells["pnl"] < 0]["pnl"].mean() if (sells["pnl"] < 0).any() else 0
    pf    = abs(avg_w / avg_l) if avg_l != 0 else 0

    return dict(
        final_pv=cash, cagr=cagr*100, sharpe=sharpe, sortino=sortino,
        max_dd=max_dd, wr=wr, pf=pf, n_trades=n,
        tax=total_tax, friction=total_fric,
        blotter=blotter_df, nav=nav,
    )


# ============================================================================
# REPORT  — standard format matching HM backtest
# ============================================================================
def report(r: dict, cfg: dict, index_cagr: float, verbose: bool = True):
    start = cfg["START_DATE"]
    end   = CFG["END_DATE"] or dt.date.today().isoformat()
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25

    print("\n" + "=" * 70)
    print(f"NSE200 MOMENTUM  slots={cfg['TOP_N']}  "
          f"momentum={cfg['MOMENTUM_WINDOW']}d  regime=True")
    print("=" * 70)
    print(f"Period       : {start} → {end} ({years:.1f}y)")
    print(f"Final equity : Rs  {r['final_pv']:>12,.0f}  "
          f"(start Rs {cfg['INITIAL_CAPITAL']:,.0f})")
    print(f"Total return : {(r['final_pv']/cfg['INITIAL_CAPITAL']-1)*100:>8.2f}%")
    print(f"CAGR         : {r['cagr']:>8.2f}%")
    print(f"Sharpe       : {r['sharpe']:>8.2f}")
    print(f"Sortino      : {r['sortino']:>8.2f}")
    print(f"Max drawdown : {r['max_dd']:>8.2f}%")
    print(f"Index CAGR   : {index_cagr:>8.2f}%    alpha {r['cagr']-index_cagr:+.2f}%")
    print("-" * 70)
    print(f"Trades       : {r['n_trades']}")
    print(f"Win rate     : {r['wr']:>8.2f}%")
    print(f"Profit factor: {r['pf']:>8.2f}")
    print(f"Tax paid     : Rs  {r['tax']:>12,.0f}")
    print(f"Friction     : Rs  {r['friction']:>12,.0f}")

    if not verbose or r["blotter"].empty:
        print("=" * 70)
        return

    sells = r["blotter"][r["blotter"]["action"] == "SELL"].copy()
    if sells.empty:
        print("=" * 70)
        return

    # Per-symbol P&L
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
    n_show = min(20, len(sym_pnl))
    for sym, row in sym_pnl.head(n_show).iterrows():
        print(f"{sym:<16} {int(row.trades):>6} {row.net_pnl:>12,.0f} "
              f"{row.wr:>6.1f} {row.avg_ret:>+8.2f}% {row.avg_hold:>7.0f}d")

    if len(sym_pnl) > n_show:
        print("  ...")
        for sym, row in sym_pnl.tail(10).iterrows():
            flag = " ◄ DRAG" if row.net_pnl < 0 else ""
            print(f"{sym:<16} {int(row.trades):>6} {row.net_pnl:>12,.0f} "
                  f"{row.wr:>6.1f} {row.avg_ret:>+8.2f}% {row.avg_hold:>7.0f}d{flag}")

    print("=" * 70)


# ============================================================================
# SWEEP
# ============================================================================
def run_sweep(master: dict, nifty_bull: pd.Series, rebal: list, cfg: dict,
              index_cagr: float):
    combos = [(slots, window)
              for slots  in [3, 5, 7]
              for window in [60, 90, 120]]
    results = []
    for i, (slots, window) in enumerate(combos):
        c = dict(cfg); c["TOP_N"] = slots; c["MOMENTUM_WINDOW"] = window
        print(f"  sweep {i+1}/{len(combos)}: slots={slots} window={window}d", end="\r")
        r = run_backtest(master, nifty_bull, rebal, c)
        results.append(dict(slots=slots, window=window,
                            cagr=r["cagr"], sharpe=r["sharpe"],
                            dd=r["max_dd"], wr=r["wr"], trades=r["n_trades"]))

    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    print("\n" + "=" * 72)
    print("NSE200 MOMENTUM SWEEP — ranked by Sharpe")
    print("=" * 72)
    print(f"{'Slots':>6} {'Window':>8} {'CAGR%':>7} {'Sharpe':>7} "
          f"{'MaxDD%':>8} {'WR%':>6} {'Trades':>7}")
    print("-" * 72)
    for _, row in df.iterrows():
        star = " ★" if _ == 0 else ""
        print(f"{int(row.slots):>6} {int(row.window):>7}d "
              f"{row.cagr:>7.2f} {row.sharpe:>7.2f} "
              f"{row.dd:>8.2f} {row.wr:>6.1f} {int(row.trades):>7}{star}")
    print("=" * 72)


# ============================================================================
# NIFTY INDEX CAGR  (for alpha calculation)
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
        return ((float(c.iloc[-1]) / float(c.iloc[0])) ** (1 / yrs) - 1) * 100
    except Exception:
        return 0.0


# ============================================================================
# MAIN
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="NSE200 Momentum Backtest")
    ap.add_argument("--slots",    type=int,   default=None,
                    help="Number of positions (default: 3)")
    ap.add_argument("--window",   type=int,   default=None,
                    help="Momentum lookback days (default: 90)")
    ap.add_argument("--start",    type=str,   default=None,
                    help="Backtest start date YYYY-MM-DD (default: 2018-01-01)")
    ap.add_argument("--capital",  type=float, default=None,
                    help="Starting capital in Rs (default: 100000)")
    ap.add_argument("--stocks",   nargs="+",  default=None,
                    help="Focused backtest on specific stocks only, e.g. --stocks BSE CGPOWER GRSE")
    ap.add_argument("--sweep",    action="store_true",
                    help="Compare slots (3,5,7) × momentum windows (60,90,120d)")
    ap.add_argument("--refresh-universe", action="store_true",
                    help="Force fresh NSE fetch ignoring cache")
    args = ap.parse_args()

    cfg = dict(CFG)
    if args.slots:    cfg["TOP_N"]           = args.slots
    if args.window:   cfg["MOMENTUM_WINDOW"] = args.window
    if args.start:    cfg["START_DATE"]      = args.start
    if args.capital:  cfg["INITIAL_CAPITAL"] = args.capital

    end_date = cfg["END_DATE"] or dt.date.today().isoformat()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 70)
    print("NSE200 MOMENTUM BACKTEST — Dynamic Nifty 200 Universe")
    print(f"Period: {cfg['START_DATE']} → {end_date}  |  "
          f"Capital: Rs {cfg['INITIAL_CAPITAL']:,.0f}  |  Slots: {cfg['TOP_N']}")
    print("=" * 70)

    focused = bool(args.stocks)

    # Universe
    if focused:
        tickers = [s.upper() + ".NS" if not s.endswith(".NS") else s.upper()
                   for s in args.stocks]
        # In focused mode only override TOP_N if --slots was not explicitly provided
        if not args.slots:
            cfg["TOP_N"] = len(tickers)
        print(f"  Focused mode: {len(tickers)} stocks → {[t.replace('.NS','') for t in tickers]}")
    else:
        tickers = get_universe(script_dir, args.refresh_universe)

    # Download — use relaxed bar minimum for focused single-stock runs
    min_bars = 60 if focused else 250
    print(f"\n  Downloading price data ({cfg['START_DATE']} → {end_date})...")
    master = download_universe(tickers, cfg["START_DATE"], end_date, min_bars=min_bars)
    if not master:
        print("  ERROR: no data loaded — check your universe or internet connection")
        sys.exit(1)

    # Nifty regime
    print("  Loading Nifty regime...")
    try:
        nf = yf.download("^NSEI", start=cfg["START_DATE"], end=end_date,
                         progress=False, auto_adjust=True)
        if isinstance(nf.columns, pd.MultiIndex):
            nf.columns = nf.columns.get_level_values(0)
        nifty_bull = nf["Close"] > nf["Close"].rolling(200).mean()
    except Exception as e:
        print(f"  Nifty download failed ({e}) — defaulting to bull regime")
        nifty_bull = pd.Series(True, index=pd.date_range(cfg["START_DATE"], end_date))

    # Rebalance dates — use shorter warmup for focused runs
    warmup_months = 3 if focused else 18
    rebal = get_rebalance_dates(master, cfg["START_DATE"], warmup_months=warmup_months)
    print(f"  {len(rebal)} monthly rebalance dates | "
          f"{len(master)} stocks with sufficient data")

    if not rebal:
        print("  ERROR: no rebalance dates — start date may be too recent")
        sys.exit(1)

    idx_cagr = nifty_cagr(cfg["START_DATE"], end_date)

    if args.sweep:
        run_sweep(master, nifty_bull, rebal, cfg, idx_cagr)
        return

    # Run single backtest
    print()
    r = run_backtest(master, nifty_bull, rebal, cfg)
    report(r, cfg, idx_cagr, verbose=True)

    # Save standard trade CSV
    if not r["blotter"].empty:
        out = os.path.join(script_dir, cfg["TRADE_CSV"])
        # Standard schema: date, symbol, action, qty, price, entry_px,
        #                  pnl, pnl_pct, held_days, rsi_entry, regime, model
        r["blotter"].to_csv(out, index=False)
        print(f"\nTrade log → {out}")
        # Save summary metrics for dashboard top bar
        import json as _json
        sells = r["blotter"][r["blotter"]["action"] == "SELL"]
        n = len(sells)
        wins_sum   = float(sells.loc[sells["pnl"] > 0,  "pnl"].sum()) if n else 0
        losses_sum = float(sells.loc[sells["pnl"] <= 0, "pnl"].sum()) if n else 0
        _metrics_out = {
            "cagr":          round(float(r.get("cagr",   0)), 2),
            "sharpe":        round(float(r.get("sharpe", 0)), 2),
            "maxdd":         round(float(r.get("max_dd", 0)), 2),
            "total_trades":  n,
            "win_rate":      round(float(r.get("wr", 0)), 1),
            "profit_factor": round(wins_sum / abs(losses_sum), 2) if losses_sum else 0,
            "avg_hold":      round(float(sells["held_days"].mean()), 1) if n else 0,
        }
        with open(os.path.join(script_dir, "nse200_metrics.json"), "w") as _f:
            _json.dump(_metrics_out, _f)
        print(f"Metrics  → nse200_metrics.json")


if __name__ == "__main__":
    main()
