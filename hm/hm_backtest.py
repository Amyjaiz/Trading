"""
Hilega Milega (NK / Nitish Kumar) backtest for Indian (NSE) equities.
================================================================================
Indicator construction (verified):
    All three lines are computed on RSI(9).
        black  = RSI(9)             -> "Strength"
        green  = EMA(3) of RSI      -> "Price"  (fast momentum visual only)
        red    = WMA(21) of RSI     -> "Volume" (slow, actual exit trigger)
    50 is the bull/bear midline.

Entry modes (ENTRY_MODE):
    'stack_hold'    RSI > WMA(21) AND RSI > 50. Entry on first day condition true.
                    EMA(3) is computed but not a hard gate — it's a momentum visual.
    'rsi_wma_cross' RSI crosses above WMA(21 of RSI).
    'rsi50_cross'   RSI crosses above 50.

Exit modes (EXIT_MODE):
    'wma_or_50'     Exit when RSI drops below WMA OR below 50. Respects MIN_HOLD_DAYS.
    'rsi50'         Exit only on RSI < 50. Respects MIN_HOLD_DAYS.
    'rsi_wma'       Exit only on RSI crossing below WMA. Respects MIN_HOLD_DAYS.
    'ema_break'     RSI crosses below EMA(3) — fast, not recommended (causes churn).
    'atr_trail'     2.5×ATR trailing stop on price (no MIN_HOLD_DAYS needed).

MIN_HOLD_DAYS: minimum calendar days before indicator exit fires.
    Prevents premature exits on first RSI wiggle after entry.
    NK's swing trades typically run 2–6 weeks; 10 days is a sensible floor.

SIZING_MODE:
    'equal'       Equal capital per slot (original behaviour).
    'vol_scale'   Allocate inversely proportional to 20-day realised volatility.
                  High-vol stocks (DBREALTY, COCHINSHIP) get smaller positions;
                  low-vol large-caps get proportionally more. Total deployed = same.
    'risk_parity' Size each trade so that 1×ATR(14) move = RISK_PCT of portfolio.
                  Classic position sizing used in Triple Screen live bot.

HARD_STOP_PCT:  If set (e.g. 0.08), any position that falls 8% below entry price
                is force-exited at next open, regardless of indicator state or
                MIN_HOLD_DAYS. Set to None to disable. This caps the DBREALTY-style
                blow-ups without adding a universal ATR trail to all trades.

Run:
    python hilega_milega_backtest.py              # live yfinance
    python hilega_milega_backtest.py --synthetic  # offline smoke-test
    python hilega_milega_backtest.py --sweep      # all entry×exit×hold combos ranked
================================================================================
"""

from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

# ============================================================================
# UNIVERSE  (223 stocks — Nifty200 + defence theme + momentum extras)
# Sources: NSE Nifty200 factsheet May 2026, Nifty India Defence index
# Removed (structural mismatch — not curve fitting):
#   Commodities:  VEDL, HINDCOPPER, HINDZINC, NATIONALUM
#   PSU banks:    UNIONBANK (+ BANKBARODA already in EXCLUDE_SYMBOLS)
#   Mid-cap IT:   MPHASIS, OFSS, REDINGTON, KPITTECH (earnings-driven, low beta)
#   Pharma/diag:  GRANULES, BIOCON, GLENMARK, MANKIND, LALPATHLAB (event-driven)
#   Structural:   INDIGO (aviation), JMFINANCIL (NBFC thin float), COROMANDEL (agrochem)
#                 DMART (high-PE defensive, 0% WR both stops), TIINDIA (auto-ancillary, 0% WR 5 trades)
#                 PAYTM (RBI/regulatory overhang, consistent drag), 360ONE (NBFC thin float)
# Borderline — watching for one more run: RAMCOCEM, JSWENERGY, SOBHA, FEDERALBNK, VIPIND
# Added — Nifty India Defence index (14 total):
#   New: GRSE, BEML, ASTRAMICRO, APARINDS, MIDHANI, PARAS
#   Already present: BEL, HAL, MAZDOCK, BDL, SOLARINDS, DATAPATTNS, TRITURBINE, BHARATFORG
# Added — capital goods / industrial momentum stocks:
#   SCHAEFFLER, TIMKEN, ELGIEQUIP, LICI, CESC
# ============================================================================
SYMBOLS = [
    "ABB","ABCAPITAL","ADANIENSOL","ADANIENT","ADANIGREEN","ADANIPORTS","ADANIPOWER",
    "AIAENG","ALKEM","AMBUJACEM","ANGELONE","APARINDS","APLAPOLLO","APOLLOHOSP","APOLLOTYRE",
    "ASHOKLEY","ASIANPAINT","ASTRAL","ASTRAMICRO","AUBANK","AUROPHARMA","AXISBANK","BAJAJ-AUTO",
    "BAJAJFINSV","BAJFINANCE","BALRAMCHIN","BANDHANBNK","BANKINDIA","BDL","BEL","BEML",
    "BHARATFORG","BHARTIARTL","BHEL","BLUESTARCO","BOSCHLTD","BPCL","BRITANNIA","BSE",
    "CANBK","CANFINHOME","CDSL","CESC","CGPOWER","CHALET","CHOLAFIN","CIPLA",
    "COALINDIA","COFORGE","COLPAL","CONCOR","CRISIL","CUB","CUMMINSIND","DABUR",
    "DALBHARAT","DATAPATTNS","DIVISLAB","DIXON","DLF","DRREDDY","ECLERX",
    "EICHERMOT","ELGIEQUIP","ENRIN","ETERNAL","EXIDEIND","FEDERALBNK","FORTIS","FSL",
    "GAIL","GMRAIRPORT","GOCOLORS","GODREJCP","GODREJPROP","GRASIM","GRSE","HAL",
    "HAVELLS","HCLTECH","HDFCAMC","HDFCBANK","HDFCLIFE","HEROMOTOCO","HINDALCO","HINDPETRO",
    "HINDUNILVR","HUDCO","ICICIAMC","ICICIBANK","ICICIGI","ICICIPRULI","IDBI","IDEA",
    "IDFCFIRSTB","IIFL","INDHOTEL","INDIANB","INDUSINDBK","INDUSTOWER","INFY","IOC",
    "IRCTC","IRFC","ITC","JBCHEPHARM","JINDALSTEL","JIOFIN","JSWENERGY","JSWSTEEL",
    "JUBLFOOD","KALYANKJIL","KEI","KOTAKBANK","KRBL","LAURUSLABS","LICHSGFIN",
    "LICI","LODHA","LT","LTF","LTM","LUPIN","M&M","M&MFIN",
    "MAHABANK","MAHLIFE","MARICO","MARUTI","MAXHEALTH","MAZDOCK","MCX","MFSL",
    "MIDHANI","MINDSPACE","MOTHERSON","MOTILALOFS","MRF","MUTHOOTFIN","NATCOPHARM","NAUKRI",
    "NAVINFLUOR","NBCC","NESTLEIND","NHPC","NMDC","NTPC","NYKAA","OBEROIRLTY",
    "OIL","ONGC","PAGEIND","PARAS","PERSISTENT","PETRONET","PFC",
    "PHOENIXLTD","PIDILITIND","PIIND","PNB","POLICYBZR","POLYCAB","POONAWALLA","POWERGRID",
    "POWERINDIA","PRESTIGE","RADICO","RAMCOCEM","RATEGAIN","RBLBANK","RECLTD","RELIANCE",
    "RVNL","SAFARI","SAIL","SBICARD","SBILIFE","SBIN","SCHAEFFLER","SHREECEM",
    "SHRIRAMFIN","SIEMENS","SOBHA","SOLARINDS","SPARC","SRF","STAR","SUNPHARMA",
    "SUPREMEIND","SUZLON","SYRMA","TANLA","TATACAP","TATACHEM","TATACOMM","TATACONSUM",
    "TATAELXSI","TATAPOWER","TATASTEEL","TCS","TECHM","THERMAX","TIMKEN",
    "TITAGARH","TITAN","TORNTPHARM","TORNTPOWER","TRENT","TRITURBINE","TVSMOTOR","ULTRACEMCO",
    "UNITDSPR","UPL","UTIAMC","VBL","VIPIND","VOLTAS","WAAREEENER","WELCORP",
    "WIPRO","YESBANK","ZEEL","ZYDUSLIFE",
]

# ============================================================================
# SECTOR MAP  — NSE sector classifications
# Used by ML features: sector_wr_hist (rolling sector win rate) and
# sector_momentum (average 20d return across sector peers).
# Sectors: CapGoods, Defence, IT, Pharma, PSUBank, PrivBank, NBFC,
#          Energy, Metal, FMCG, Auto, Realty, Infra, Insurance, Diversified
# ============================================================================
SECTOR_MAP = {
    # Capital Goods / Industrials — core winners on HM
    "ABB":"CapGoods","BHEL":"CapGoods","CGPOWER":"CapGoods","CUMMINSIND":"CapGoods",
    "ELGIEQUIP":"CapGoods","HAVELLS":"CapGoods","POLYCAB":"CapGoods","SIEMENS":"CapGoods",
    "THERMAX":"CapGoods","TIMKEN":"CapGoods","SCHAEFFLER":"CapGoods","VOLTAS":"CapGoods",
    "BLUESTARCO":"CapGoods","POWERINDIA":"CapGoods","APARINDS":"CapGoods",
    "TRITURBINE":"CapGoods","KEI":"CapGoods","ASTRAL":"CapGoods","APLAPOLLO":"CapGoods",
    "SUPREMEIND":"CapGoods","WELCORP":"CapGoods","CONCOR":"CapGoods",

    # Defence
    "BEL":"Defence","HAL":"Defence","MAZDOCK":"Defence","BDL":"Defence",
    "DATAPATTNS":"Defence","SOLARINDS":"Defence","GRSE":"Defence","BEML":"Defence",
    "ASTRAMICRO":"Defence","MIDHANI":"Defence","PARAS":"Defence","BHARATFORG":"Defence",

    # IT Services — earnings-driven, low HM WR
    "TCS":"IT","INFY":"IT","HCLTECH":"IT","WIPRO":"IT","TECHM":"IT",
    "COFORGE":"IT","PERSISTENT":"IT","MPHASIS":"IT","OFSS":"IT","LTM":"IT",
    "KPITTECH":"IT","TATAELXSI":"IT","TATACOMM":"IT","NAUKRI":"IT",
    "RATEGAIN":"IT","TANLA":"IT","ECLERX":"IT","REDINGTON":"IT",

    # Pharma / Healthcare — USFDA-driven, structural HM mismatch
    "SUNPHARMA":"Pharma","DRREDDY":"Pharma","CIPLA":"Pharma","LUPIN":"Pharma",
    "ALKEM":"Pharma","AUROPHARMA":"Pharma","DIVISLAB":"Pharma","ZYDUSLIFE":"Pharma",
    "TORNTPHARM":"Pharma","NATCOPHARM":"Pharma","SPARC":"Pharma","LAURUSLABS":"Pharma",
    "GRANULES":"Pharma","BIOCON":"Pharma","GLENMARK":"Pharma","MANKIND":"Pharma",
    "APOLLOHOSP":"Pharma","FORTIS":"Pharma","MAXHEALTH":"Pharma","LALPATHLAB":"Pharma",
    "JBCHEPHARM":"Pharma","NAVINFLUOR":"Pharma","PIIND":"Pharma",

    # PSU Banks — structural drag
    "SBIN":"PSUBank","PNB":"PSUBank","BANKINDIA":"PSUBank","CANBK":"PSUBank",
    "UNIONBANK":"PSUBank","MAHABANK":"PSUBank","INDIANB":"PSUBank",
    "BANKBARODA":"PSUBank","IDBI":"PSUBank",

    # Private Banks
    "HDFCBANK":"PrivBank","ICICIBANK":"PrivBank","AXISBANK":"PrivBank",
    "KOTAKBANK":"PrivBank","INDUSINDBK":"PrivBank","FEDERALBNK":"PrivBank",
    "AUBANK":"PrivBank","BANDHANBNK":"PrivBank","IDFCFIRSTB":"PrivBank",
    "RBLBANK":"PrivBank","CUB":"PrivBank","YESBANK":"PrivBank",

    # NBFCs / Financials
    "BAJFINANCE":"NBFC","BAJAJFINSV":"NBFC","CHOLAFIN":"NBFC","MUTHOOTFIN":"NBFC",
    "M&MFIN":"NBFC","LICHSGFIN":"NBFC","POONAWALLA":"NBFC","ABCAPITAL":"NBFC",
    "IIFL":"NBFC","CANFINHOME":"NBFC","LTF":"NBFC","SHRIRAMFIN":"NBFC",
    "JMFINANCIL":"NBFC","360ONE":"NBFC","MOTILALOFS":"NBFC","ANGELONE":"NBFC",
    "MFSL":"NBFC","JIOFIN":"NBFC","BSE":"NBFC","MCX":"NBFC","CDSL":"NBFC",
    "CRISIL":"NBFC","UTIAMC":"NBFC","HDFCAMC":"NBFC","ICICIAMC":"NBFC",

    # Energy / Oil & Gas
    "RELIANCE":"Energy","ONGC":"Energy","BPCL":"Energy","IOC":"Energy",
    "GAIL":"Energy","HINDPETRO":"Energy","OIL":"Energy","PETRONET":"Energy",
    "ADANIGREEN":"Energy","ADANIPOWER":"Energy","TATAPOWER":"Energy",
    "JSWENERGY":"Energy","NTPC":"Energy","POWERGRID":"Energy","NHPC":"Energy",
    "PFC":"Energy","RECLTD":"Energy","IRFC":"Energy","HUDCO":"Energy",
    "RVNL":"Energy","IREDA":"Energy","ADANIENSOL":"Energy","WAAREEENER":"Energy",

    # Metals & Mining — commodity, structural HM mismatch
    "TATASTEEL":"Metal","JSWSTEEL":"Metal","SAIL":"Metal","JINDALSTEL":"Metal",
    "HINDALCO":"Metal","VEDL":"Metal","NMDC":"Metal","COALINDIA":"Metal",
    "HINDCOPPER":"Metal","NATIONALUM":"Metal","HINDZINC":"Metal","WELCORP":"Metal",

    # FMCG / Consumer
    "HINDUNILVR":"FMCG","ITC":"FMCG","NESTLEIND":"FMCG","BRITANNIA":"FMCG",
    "DABUR":"FMCG","MARICO":"FMCG","COLPAL":"FMCG","GODREJCP":"FMCG",
    "TATACONSUM":"FMCG","UNITDSPR":"FMCG","VBL":"FMCG","RADICO":"FMCG",
    "KRBL":"FMCG","BALRAMCHIN":"FMCG","EIDPARRY":"FMCG","JUBLFOOD":"FMCG",
    "GOCOLORS":"FMCG","KALYANKJIL":"FMCG","SAFARI":"FMCG","TITAN":"FMCG",
    "PAGEIND":"FMCG","TRENT":"FMCG","NYKAA":"FMCG","ETERNAL":"FMCG",
    "DMART":"FMCG","LICI":"FMCG",

    # Auto & Auto Ancillary
    "MARUTI":"Auto","TVSMOTOR":"Auto","EICHERMOT":"Auto","BAJAJ-AUTO":"Auto",
    "M&M":"Auto","HEROMOTOCO":"Auto","ASHOKLEY":"Auto","TATAMOTORS":"Auto",
    "MOTHERSON":"Auto","BOSCHLTD":"Auto","APOLLOTYRE":"Auto","EXIDEIND":"Auto",
    "TIINDIA":"Auto","SCHAEFFLER":"Auto",

    # Realty
    "DLF":"Realty","PRESTIGE":"Realty","SOBHA":"Realty","OBEROIRLTY":"Realty",
    "LODHA":"Realty","GODREJPROP":"Realty","PHOENIXLTD":"Realty","CHALET":"Realty",
    "MINDSPACE":"Realty","DBREALTY":"Realty",

    # Infrastructure
    "LT":"Infra","NBCC":"Infra","GMRAIRPORT":"Infra","ADANIPORTS":"Infra",
    "CONCOR":"Infra","TITAGARH":"Infra","BHEL":"Infra","RVNL":"Infra",

    # Insurance
    "SBILIFE":"Insurance","HDFCLIFE":"Insurance","ICICIGI":"Insurance",
    "ICICIPRULI":"Insurance","MFSL":"Insurance",

    # Diversified / Others
    "ADANIENT":"Diversified","GRASIM":"Diversified","BAJAJHLDNG":"Diversified",
    "TATACHEM":"Diversified","PIDILITIND":"Diversified","ASIANPAINT":"Diversified",
    "RAMCOCEM":"Diversified","DALBHARAT":"Diversified","SHREECEM":"Diversified",
    "AMBUJACEM":"Diversified","ULTRACEMCO":"Diversified","BHARAT":"Diversified",
    "INDHOTEL":"Diversified","INDIGO":"Diversified","IRCTC":"Diversified",
    "MAZDOCK":"Diversified","IDEA":"Diversified","ZEEL":"Diversified",
    "STAR":"Diversified","NETWORK18":"Diversified","BHARTIARTL":"Diversified",
    "INDUSTOWER":"Diversified","COROMANDEL":"Diversified","FSL":"Diversified",
    "PSUBNKBEES":"PSUBank","SYRMA":"CapGoods","MAHLIFE":"Realty",
    "TATACAP":"NBFC","POLICYBZR":"Insurance","AIAENG":"CapGoods",
    "JSWSTEEL":"Metal","PIIND":"Pharma","DELHIVERY":"Infra","PAYTM":"NBFC",
    "MAHABANK":"PSUBank","IDBI":"PSUBank","WARBURTNS":"Diversified",
    "WAAREEENER":"Energy","ENRIN":"Energy","LICI":"Insurance",
    "NMDC":"Metal","ADANIENSOL":"Energy","LTM":"IT","CESC":"Energy",
    "HINDPETRO":"Energy","SAIL":"Metal","BIOCON":"Pharma",
    "COCHINSHIP":"Defence","CHENNPETRO":"Energy","BANKBARODA":"PSUBank",
    "SUPREMEIND":"CapGoods","ELGIEQUIP":"CapGoods","TIMKEN":"CapGoods",
}

def get_sector(sym: str) -> str:
    return SECTOR_MAP.get(sym, "Diversified")  # default bucket for unmapped stocks

# ============================================================================
CFG = dict(
    SYMBOLS=SYMBOLS,
    INDEX_SYMBOL="^NSEI",
    YF_SUFFIX=".NS",

    START="2024-01-01",             # 2-year backtest window for live use
                                    # Change to "2010-01-01" for full ML training run
    END=None,                       # None = today

    # indicator
    RSI_LEN=9,
    EMA_LEN=3,
    WMA_LEN=21,
    MID=50.0,

    # signal
    ENTRY_MODE="stack_hold",        # stack_hold | rsi_wma_cross | rsi50_cross
    EXIT_MODE="rsi50_and_vwap",     # ★ BEST from vwapsweep: CAGR 16.99% Sharpe 1.17
                                    # exits when RSI<50 OR Close<weekly VWAP
                                    # options: wma_or_50 | rsi50_only | rsi_wma |
                                    #          ema_break | atr_trail | vwap_break |
                                    #          wma50_and_vwap | rsi50_and_vwap
    MIN_HOLD_DAYS=10,               # calendar days before indicator exit can fire

    # regime filter
    USE_REGIME_FILTER=True,
    REGIME_SMA=200,

    # ATR (only for EXIT_MODE='atr_trail')
    ATR_LEN=14,
    ATR_MULT=2.5,

    # portfolio
    INITIAL_CAPITAL=100_000.0,
    MAX_POSITIONS=5,
    RANK_BY="rsi",                  # rank competing signals by rsi value

    # position sizing
    SIZING_MODE="atr_pct",          # 'equal' | 'vol_scale' | 'atr_pct' | 'risk_parity'
                                    # atr_pct: size inversely to ATR/price — forward-looking,
                                    #   doesn't lag reversals the way realised vol does
    VOL_WINDOW=20,                  # lookback for vol_scale realised vol
    RISK_PCT=0.02,                  # risk per trade as fraction of portfolio (risk_parity only)

    # hard stop loss per trade (fires before MIN_HOLD_DAYS)
    HARD_STOP_PCT=0.08,             # exit if price drops 8% below entry; None to disable

    # cooldown after a hard stop triggers on a stock
    STOP_COOLDOWN_DAYS=30,          # days to blacklist stock after stop-out; 0 = no cooldown

    # ── PYRAMIDING ────────────────────────────────────────────────────────────────
    # Add to a winning position when the HM entry signal fires again on a stock
    # you already hold. Called "adding to winners" in trend-following.
    #
    # Rules:
    #   - Only adds if current price is ABOVE the original entry price (not adding to losers)
    #   - Add-on size is PYRAMID_SIZE × original allocation (smaller than initial)
    #   - Stop updates to protect blended cost: new_stop = blended_cost × (1 - HARD_STOP_PCT)
    #   - Max PYRAMID_MAX add-ons per position (so up to PYRAMID_MAX+1 total entries)
    #   - Pyramid add counts toward slot usage (each add uses a sub-slot)
    #
    # Set PYRAMID_MAX=0 to disable pyramiding entirely (original behaviour).
    PYRAMID_MAX=0,                  # 0 = off | 1 or 2 recommended
    PYRAMID_SIZE=0.5,               # add-on alloc as fraction of original slot alloc

    # ── VWAP ──────────────────────────────────────────────────────────────────
    # weekly_vwap: TP*Vol cumulated Mon→Fri, resets each Monday.
    # anchored_52w: anchored from 52-week low bar — tested WORSE on NSE swings.
    # CONFIRMED from vwapsweep: weekly VWAP outperforms anchored_52w across all modes.
    USE_VWAP_ENTRY=False,           # ★ keep False — VWAP entry filter reduces alpha
    VWAP_TYPE="weekly",             # ★ weekly beats anchored_52w on NSE daily data
    VWAP_EXIT_ONLY=False,           # adds vwap_break as extra OR to any exit mode
    # costs
    COST_BPS=15.0,                  # round-trip bps (brokerage + STT + slippage)
    APPLY_TAX=True,
    STCG_RATE=0.20,
    LTCG_RATE=0.125,

    # structurally incompatible stocks — commodity cyclicals and parabolic blow-ups
    # that trend violently and reverse; HM indicator cannot time their exits cleanly.
    # This is NOT curve fitting — these are removed for behavioural/structural reasons.
    EXCLUDE_SYMBOLS={
        "DBREALTY",    # real estate speculative, illiquid float, violent reversals
        "COCHINSHIP",  # defence PSU, moves on govt order news not momentum
        "EIDPARRY",    # sugar commodity, mean-reverting by nature
        "CHENNPETRO",  # refinery commodity margin play
        "BANKBARODA",  # PSU bank structural drag (same issue as BANKINDIA in Triple Screen)
    },

    # path to your NSE200 momentum model's universe cache
    # used when running with --nifty200 flag
    NIFTY200_CACHE_PATH=r"C:\ml_mom\nifty200_cache.csv",

    # ── ML LAYER ──────────────────────────────────────────────────────────────
    # The ML classifier is trained on ALL signal days across a larger "dirty"
    # universe (including previously removed stocks). It learns why signals fail
    # on commodity/pharma/IT stocks and rejects them — so we don't need to
    # manually curate the universe as aggressively.
    USE_ML=False,                   # set True to enable ML filter at backtest time
    ML_MODEL_PATH="hm_signal_clf.pkl",   # saved model file
    ML_THRESHOLD=0.45,              # min predicted win-prob to accept a trade
    ML_MIN_SIGNALS=5,               # stocks with fewer training signals auto-pass
    ML_TRAIN_END="2022-12-31",      # walk-forward split: train on data up to here
                                    # test (backtest with ML) uses 2023-01-01 onward
    # Extra stocks added back for ML training only (not traded unless ML accepts)
    # These are the "structural mismatch" stocks we removed — the ML learns from
    # their failures so it can reject bad signals on similar stocks in the main universe
    ML_TRAINING_EXTRA=[
        # Commodities
        "VEDL","HINDCOPPER","HINDZINC","NATIONALUM","COROMANDEL",
        # PSU banks
        "UNIONBANK","MAHABANK",
        # Mid-cap IT (earnings-driven)
        "MPHASIS","OFSS","REDINGTON","KPITTECH","LTM",
        # Pharma/diagnostics (event-driven)
        "GRANULES","BIOCON","GLENMARK","MANKIND","LALPATHLAB",
        # Structural mismatches
        "INDIGO","JMFINANCIL","DMART","TIINDIA","PAYTM","360ONE",
        "DBREALTY","COCHINSHIP","EIDPARRY","CHENNPETRO","BANKBARODA",
        "GMRAIRPORT","BHARTIARTL","DRREDDY","DALBHARAT","VIPIND",
        "AIAENG","ASTRAL","RAMCOCEM","JSWENERGY","SOBHA",
    ],
)


# ============================================================================
# INDICATORS
# ============================================================================
def wilder_rsi(close: pd.Series, n: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0.0)
    loss     = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0/n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0/n, adjust=False, min_periods=n).mean()
    rs  = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    return rsi


def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def calc_atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, lo, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/n, adjust=False, min_periods=n).mean()


def compute_vwap(df: pd.DataFrame, vwap_type: str = "weekly") -> pd.Series:
    """
    Daily-bar VWAP proxies — both meaningful on end-of-day data.

    weekly_vwap:
        Typical price (H+L+C)/3 × Volume, cumulated from Monday each week
        and divided by cumulative volume. Resets every Monday.
        Captures where institutions traded on average this week.

    anchored_52w:
        Same TP×Vol cumulation but anchored from the bar where the
        52-week rolling low was set. Measures average cost basis of
        buyers since the last major bottom.
    """
    tp  = (df["High"] + df["Low"] + df["Close"]) / 3.0
    vol = df["Volume"].replace(0, np.nan).fillna(1)
    tpv = tp * vol

    if vwap_type == "weekly":
        # Day-of-week: Monday=0. Restart cumsum at each Monday.
        dow         = pd.Series(df.index.dayofweek, index=df.index)
        week_group  = (dow == 0).cumsum()             # group id increments each Monday
        cum_tpv     = tpv.groupby(week_group).cumsum()
        cum_vol     = vol.groupby(week_group).cumsum()
        return cum_tpv / cum_vol

    elif vwap_type == "anchored_52w":
        # Find rolling 252-bar (52-week) low bar — anchor changes as new lows form
        roll_low    = df["Close"].rolling(252, min_periods=1).min()
        anchor_bar  = roll_low.eq(df["Close"])        # True on the day a new 52w low sets
        anchor_grp  = anchor_bar.cumsum()             # group increments at each new low
        cum_tpv     = tpv.groupby(anchor_grp).cumsum()
        cum_vol     = vol.groupby(anchor_grp).cumsum()
        return cum_tpv / cum_vol

    else:
        raise ValueError(f"Unknown VWAP_TYPE: {vwap_type}")


def compute_hm(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    df["rsi"]     = wilder_rsi(df["Close"], cfg["RSI_LEN"])
    df["hm_ema"]  = df["rsi"].ewm(span=cfg["EMA_LEN"], adjust=False).mean()
    df["hm_wma"]  = wma(df["rsi"], cfg["WMA_LEN"])
    df["atr"]     = calc_atr(df, cfg["ATR_LEN"])
    df["atr_pct"] = df["atr"] / df["Close"]
    log_ret       = np.log(df["Close"] / df["Close"].shift(1))
    df["rvol"]    = log_ret.rolling(cfg.get("VOL_WINDOW", 20)).std()
    # VWAP (always computed; used when USE_VWAP_ENTRY=True or EXIT_MODE involves vwap)
    df["vwap"]    = compute_vwap(df, cfg.get("VWAP_TYPE", "weekly"))
    df["above_vwap"] = df["Close"] > df["vwap"]
    return df


# ============================================================================
# SIGNALS  (indicator logic only — MIN_HOLD_DAYS enforced in engine)
# ============================================================================
def make_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    r, e, w, mid = df["rsi"], df["hm_ema"], df["hm_wma"], cfg["MID"]

    # ── ENTRY ──────────────────────────────────────────────────────────────
    if cfg["ENTRY_MODE"] == "stack_hold":
        bull = (r > w) & (r > mid)
        df["entry"] = bull & ~bull.shift(1, fill_value=False)
    elif cfg["ENTRY_MODE"] == "rsi_wma_cross":
        df["entry"] = (r > w) & (r.shift(1) <= w.shift(1))
    elif cfg["ENTRY_MODE"] == "rsi50_cross":
        df["entry"] = (r > mid) & (r.shift(1) <= mid)
    else:
        raise ValueError(f"Unknown ENTRY_MODE: {cfg['ENTRY_MODE']}")

    # VWAP entry filter — only enter when Close > VWAP
    if cfg.get("USE_VWAP_ENTRY", False) and "above_vwap" in df.columns:
        df["entry"] = df["entry"] & df["above_vwap"]

    # ── EXIT ───────────────────────────────────────────────────────────────
    if cfg["EXIT_MODE"] == "wma_or_50":
        bear = (r < w) | (r < mid)
        df["exit"] = bear & ~bear.shift(1, fill_value=False)

    elif cfg["EXIT_MODE"] == "rsi50_only":
        # Looser: ignore WMA wobbles, only exit on RSI < 50. Holds longer.
        df["exit"] = (r < mid) & (r.shift(1) >= mid)

    elif cfg["EXIT_MODE"] == "rsi_wma":
        df["exit"] = (r < w) & (r.shift(1) >= w.shift(1))

    elif cfg["EXIT_MODE"] == "ema_break":
        # Fast exit on RSI < EMA(3). Cuts losses early but churns.
        df["exit"] = (r < e) & (r.shift(1) >= e.shift(1))

    elif cfg["EXIT_MODE"] == "atr_trail":
        df["exit"] = False          # handled dynamically in engine

    elif cfg["EXIT_MODE"] == "vwap_break":
        # Exit when Close drops below weekly VWAP — captures institutional selling
        vwap_brk = df["Close"] < df["vwap"]
        df["exit"] = vwap_brk & ~vwap_brk.shift(1, fill_value=False)

    elif cfg["EXIT_MODE"] == "wma50_and_vwap":
        # Hybrid — tightest: exit on (RSI<WMA or RSI<50) OR vwap_break
        bear     = (r < w) | (r < mid)
        vwap_brk = df["Close"] < df["vwap"]
        combined = bear | vwap_brk
        df["exit"] = combined & ~combined.shift(1, fill_value=False)

    elif cfg["EXIT_MODE"] == "rsi50_and_vwap":
        # RSI<50 OR vwap_break — middle ground
        combined = (r < mid) | (df["Close"] < df["vwap"])
        df["exit"] = combined & ~combined.shift(1, fill_value=False)

    else:
        raise ValueError(f"Unknown EXIT_MODE: {cfg['EXIT_MODE']}")

    # VWAP overlay: add vwap_break as extra OR to any non-vwap exit mode
    if cfg.get("VWAP_EXIT_ONLY", False) and "vwap" in df.columns \
            and cfg["EXIT_MODE"] not in ("vwap_break","wma50_and_vwap","rsi50_and_vwap"):
        vwap_brk = df["Close"] < df["vwap"]
        extra    = vwap_brk & ~vwap_brk.shift(1, fill_value=False)
        df["exit"] = df["exit"] | extra

    return df


# ============================================================================
# DATA
# ============================================================================
def load_yf(cfg: dict, symbols_override: list | None = None):
    import yfinance as yf
    exclude = cfg.get("EXCLUDE_SYMBOLS", set())
    symbols = symbols_override if symbols_override is not None else cfg["SYMBOLS"]
    symbols = [s for s in symbols if s not in exclude]

    data = {}
    for sym in symbols:
        ticker = sym + cfg["YF_SUFFIX"]
        d = yf.download(ticker, start=cfg["START"], end=cfg["END"],
                        auto_adjust=True, progress=False)
        if d is None or d.empty:
            ticker_bo = sym + ".BO"
            d = yf.download(ticker_bo, start=cfg["START"], end=cfg["END"],
                            auto_adjust=True, progress=False)
            if d is None or d.empty:
                print(f"  ! skipping {sym}")
                continue
            print(f"  ~ {sym}: using .BO fallback")
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        data[sym] = d[["Open","High","Low","Close","Volume"]].dropna()

    idx = yf.download(cfg["INDEX_SYMBOL"], start=cfg["START"], end=cfg["END"],
                      auto_adjust=True, progress=False)
    if isinstance(idx.columns, pd.MultiIndex):
        idx.columns = idx.columns.get_level_values(0)
    return data, idx[["Open","High","Low","Close"]].dropna()


def load_nifty200_universe(cfg: dict) -> list[str]:
    """
    Read universe from your NSE200 momentum model's nifty200_cache.csv.
    The cache stores tickers with .NS suffix; we strip it to match our convention.
    Falls back to CFG SYMBOLS if file not found.
    """
    cache_path = cfg.get("NIFTY200_CACHE_PATH", r"C:\ml_mom\nifty200_cache.csv")
    try:
        df = pd.read_csv(cache_path)
        # Cache column is typically 'ticker' or first column; strip .NS suffix
        col = df.columns[0]
        syms = df[col].str.replace(r"\.NS$", "", regex=True).str.strip().tolist()
        exclude = cfg.get("EXCLUDE_SYMBOLS", set())
        syms = [s for s in syms if s not in exclude]
        print(f"[nifty200] loaded {len(syms)} symbols from {cache_path}")
        return syms
    except FileNotFoundError:
        print(f"  ! nifty200_cache.csv not found at {cache_path}, falling back to CFG SYMBOLS")
        exclude = cfg.get("EXCLUDE_SYMBOLS", set())
        return [s for s in cfg["SYMBOLS"] if s not in exclude]


def make_synthetic(cfg: dict, seed: int = 7):
    rng   = np.random.default_rng(seed)
    dates = pd.bdate_range(cfg["START"], "2025-12-31")
    n     = len(dates)

    def gbm(mu, sig, p0):
        ret   = rng.normal(mu, sig, n)
        close = p0 * np.exp(np.cumsum(ret))
        op    = close * (1 + rng.normal(0, sig/2, n))
        hi    = np.maximum(op, close) * (1 + np.abs(rng.normal(0, sig, n)))
        lo    = np.minimum(op, close) * (1 - np.abs(rng.normal(0, sig, n)))
        vol   = rng.integers(int(1e5), int(5e6), n)
        return pd.DataFrame({"Open":op,"High":hi,"Low":lo,
                             "Close":close,"Volume":vol}, index=dates)

    # Use only first 30 symbols for speed in smoke-test
    syms = cfg["SYMBOLS"][:30]
    data = {}
    for s in syms:
        data[s] = gbm(rng.normal(0.0004,0.0003), rng.uniform(0.012,0.022),
                      rng.uniform(80,3000))
    idx = gbm(0.0003, 0.010, 18000)[["Open","High","Low","Close"]]
    return data, idx


# ============================================================================
# ML LAYER  — signal classifier
# ============================================================================
FEATURE_COLS = [
    "rsi_at_entry",      # RSI value at signal — strength of momentum
    "wma_gap",           # RSI minus WMA(21 of RSI) — momentum lead
    "ema_gap",           # RSI minus EMA(3 of RSI) — fast momentum
    "atr_pct",           # ATR/price — normalised volatility at entry
    "vol_surge",         # signal-day volume / 20d avg volume
    "dist_52w_high",     # (price - 52w high) / 52w high — position in range
    "dist_ema50",        # (price - EMA50) / EMA50 — trend structure
    "nifty_rsi",         # Nifty RSI(9) at entry — market strength
    "nifty_ret5",        # Nifty 5-day return — short-term market trend
    "nifty_ret20",       # Nifty 20-day return — medium-term market trend
    "days_since_signal", # days since last signal on this stock — spacing
    "prev_win",          # 1 if last closed trade on this stock was a win
    "sector_wr_hist",    # rolling historical WR of all HM signals in this sector
                         # captures: CapGoods/Defence win ~70%, Pharma/Metal ~40%
    "sector_momentum",   # avg 20d price return of sector peers — sector in momentum phase?
]


def build_feature_rows(prepped: dict, trades_df: pd.DataFrame,
                       index_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    For every completed trade, extract the feature vector at the signal day
    (entry_date) and label it 1 (win) or 0 (loss).
    Called after a full backtest run to generate training data.
    No lookahead: sector_wr_hist uses only trades closed BEFORE entry_date.
    """
    if trades_df.empty:
        return pd.DataFrame()

    # Nifty derived series
    idx = index_df.copy()
    idx["nifty_rsi"]   = wilder_rsi(idx["Close"], cfg["RSI_LEN"])
    idx["nifty_ret5"]  = idx["Close"].pct_change(5)
    idx["nifty_ret20"] = idx["Close"].pct_change(20)

    # Precompute 20d returns for every stock — used for sector_momentum
    ret20 = {}
    for sym, df in prepped.items():
        ret20[sym] = df["Close"].pct_change(20)

    # Build sector peer lists
    from collections import defaultdict
    sector_peers: dict[str, list] = defaultdict(list)
    for sym in prepped:
        sector_peers[get_sector(sym)].append(sym)

    # Track last signal date, last trade outcome, and running sector WR
    last_signal:  dict[str, pd.Timestamp] = {}
    last_win:     dict[str, int]           = {}
    # sector_outcomes: sector -> list of (date, outcome) for rolling WR
    sector_outcomes: dict[str, list] = defaultdict(list)

    rows = []
    for _, tr in trades_df.sort_values("entry").iterrows():
        sym   = tr["symbol"]
        edate = pd.Timestamp(tr["entry"])
        df    = prepped.get(sym)
        if df is None or edate not in df.index:
            continue

        row     = df.loc[edate]
        sector  = get_sector(sym)

        # Nifty features on entry date
        nifty_row = idx.loc[edate] if edate in idx.index else None

        # 52-week high lookback
        hist     = df["Close"].loc[:edate]
        high_52w = hist.iloc[-252:].max() if len(hist) >= 5 else hist.max()

        # EMA50 of price
        ema50_val = df["Close"].ewm(span=50, adjust=False).mean().loc[edate]

        # Volume surge
        vol_20d_avg = df["Volume"].rolling(20).mean()
        vol_avg_val = vol_20d_avg.loc[edate] if edate in vol_20d_avg.index else np.nan
        vol_surge   = (df.at[edate, "Volume"] / vol_avg_val
                       if pd.notna(vol_avg_val) and vol_avg_val > 0 else 1.0)

        # Days since last signal on this stock
        days_gap = (edate - last_signal[sym]).days if sym in last_signal else 180

        # sector_wr_hist: rolling win rate of sector signals seen BEFORE this entry
        # Only uses trades already in sector_outcomes (closed before edate)
        past_sector = [(d, o) for d, o in sector_outcomes[sector] if d < edate]
        if len(past_sector) >= 3:
            sector_wr = np.mean([o for _, o in past_sector[-40:]])  # last 40 sector signals
        else:
            sector_wr = 0.55  # prior: neutral (slightly above 50% base rate)

        # sector_momentum: avg 20d return of sector peers on edate
        peer_rets = []
        for peer in sector_peers[sector]:
            if peer != sym and edate in ret20.get(peer, pd.Series()).index:
                v = ret20[peer].loc[edate]
                if pd.notna(v):
                    peer_rets.append(float(v))
        sector_mom = float(np.mean(peer_rets)) if peer_rets else 0.0

        feat = {
            "rsi_at_entry":      float(row["rsi"]) if pd.notna(row["rsi"]) else 50.0,
            "wma_gap":           float(row["rsi"] - row["hm_wma"]) if pd.notna(row["hm_wma"]) else 0.0,
            "ema_gap":           float(row["rsi"] - row["hm_ema"]) if pd.notna(row["hm_ema"]) else 0.0,
            "atr_pct":           float(row["atr_pct"]) if pd.notna(row.get("atr_pct")) else 0.02,
            "vol_surge":         float(vol_surge),
            "dist_52w_high":     float((row["Close"] - high_52w) / high_52w) if high_52w else 0.0,
            "dist_ema50":        float((row["Close"] - ema50_val) / ema50_val) if pd.notna(ema50_val) and ema50_val else 0.0,
            "nifty_rsi":         float(nifty_row["nifty_rsi"]) if nifty_row is not None and pd.notna(nifty_row["nifty_rsi"]) else 50.0,
            "nifty_ret5":        float(nifty_row["nifty_ret5"]) if nifty_row is not None and pd.notna(nifty_row["nifty_ret5"]) else 0.0,
            "nifty_ret20":       float(nifty_row["nifty_ret20"]) if nifty_row is not None and pd.notna(nifty_row["nifty_ret20"]) else 0.0,
            "days_since_signal": float(min(days_gap, 365)),
            "prev_win":          float(last_win.get(sym, 0.5)),
            "sector_wr_hist":    float(sector_wr),
            "sector_momentum":   float(sector_mom),
            "symbol":            sym,
            "entry_date":        edate,
            "label":             1 if tr["net_pnl"] > 0 else 0,
        }
        rows.append(feat)

        # Update state — append AFTER building features (no lookahead)
        last_signal[sym] = edate
        last_win[sym]    = 1 if tr["net_pnl"] > 0 else 0
        sector_outcomes[sector].append((edate, 1 if tr["net_pnl"] > 0 else 0))

    return pd.DataFrame(rows)


def train_ml_model(feature_df: pd.DataFrame, cfg: dict):
    """
    Train a gradient-boosted classifier on signal-day features.
    Uses LightGBM if available, falls back to sklearn GradientBoosting.
    Returns fitted model and feature importances.
    """
    if feature_df.empty or len(feature_df) < 50:
        print("  ! Not enough training samples — ML disabled")
        return None

    X = feature_df[FEATURE_COLS].fillna(0)
    y = feature_df["label"]

    base_wr = y.mean()
    print(f"  Training samples  : {len(X)}")
    print(f"  Base win rate     : {base_wr*100:.1f}%")
    print(f"  Class balance     : {y.sum()} wins / {(1-y).sum()} losses")

    try:
        import lightgbm as lgb
        model = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.03, max_depth=4,
            num_leaves=15, min_child_samples=20, subsample=0.8,
            colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=0.1,
            random_state=42, verbose=-1,
        )
        model_name = "LightGBM"
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        model = GradientBoostingClassifier(
            n_estimators=300, learning_rate=0.03, max_depth=3,
            min_samples_leaf=20, subsample=0.8, random_state=42,
        )
        model_name = "sklearn GBT"

    model.fit(X, y)
    print(f"  Model             : {model_name}")

    # Feature importance
    if hasattr(model, "feature_importances_"):
        imp = sorted(zip(FEATURE_COLS, model.feature_importances_),
                     key=lambda x: x[1], reverse=True)
        print("  Top features      :", " | ".join(f"{n}={v:.3f}" for n,v in imp[:5]))

    return model


def evaluate_ml_model(model, feature_df: pd.DataFrame, cfg: dict):
    """Walk-forward evaluation: train on [start, ML_TRAIN_END], test on remainder."""
    from sklearn.metrics import roc_auc_score
    train_end = pd.Timestamp(cfg.get("ML_TRAIN_END", "2022-12-31"))
    train = feature_df[feature_df["entry_date"] <= train_end]
    test  = feature_df[feature_df["entry_date"] >  train_end]

    print(f"\n  Walk-forward split: train={len(train)} test={len(test)}")
    if len(test) < 20:
        print("  ! Test set too small for reliable AUC")
        return

    X_test = test[FEATURE_COLS].fillna(0)
    y_test  = test["label"]
    probs   = model.predict_proba(X_test)[:, 1]
    auc     = roc_auc_score(y_test, probs)
    print(f"  Test AUC          : {auc:.4f}")

    # Decile table on test set
    test_copy = test.copy()
    test_copy["prob"] = probs
    test_copy["decile"] = pd.qcut(probs, 10, labels=False, duplicates="drop")
    decile_tbl = (test_copy.groupby("decile")["label"]
                  .agg(n="count", wr="mean")
                  .reset_index())
    print("  Decile WR (test)  :")
    for _, r in decile_tbl.iterrows():
        bar = "█" * int(r.wr * 20)
        print(f"    D{int(r.decile):02d}  n={int(r.n):3d}  WR={r.wr*100:5.1f}%  {bar}")


def save_model(model, path: str):
    import pickle
    with open(path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Model saved → {path}")


def load_model(path: str):
    import pickle, os
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def build_live_features(sym: str, row: pd.Series, df: pd.DataFrame,
                        edate: pd.Timestamp, index_df: pd.DataFrame,
                        cfg: dict, last_signal: dict, last_win: dict,
                        sector_outcomes: dict, prepped_all: dict) -> dict:
    """Build feature vector for a live candidate entry (no label)."""
    idx = index_df.copy()
    idx["nifty_rsi"]   = wilder_rsi(idx["Close"], cfg["RSI_LEN"])
    idx["nifty_ret5"]  = idx["Close"].pct_change(5)
    idx["nifty_ret20"] = idx["Close"].pct_change(20)

    nifty_row = idx.loc[edate] if edate in idx.index else None
    hist      = df["Close"].loc[:edate]
    high_52w  = hist.iloc[-252:].max() if len(hist) >= 5 else hist.max()
    ema50_val = df["Close"].ewm(span=50, adjust=False).mean().loc[edate]
    vol_20d   = df["Volume"].rolling(20).mean()
    vol_avg   = vol_20d.loc[edate] if edate in vol_20d.index else np.nan
    vol_surge = (df.at[edate, "Volume"] / vol_avg
                 if pd.notna(vol_avg) and vol_avg > 0 else 1.0)
    days_gap  = (edate - last_signal[sym]).days if sym in last_signal else 180

    # Sector features
    sector = get_sector(sym)
    past_sector = [(d, o) for d, o in sector_outcomes.get(sector, []) if d < edate]
    sector_wr   = float(np.mean([o for _, o in past_sector[-40:]])) if len(past_sector) >= 3 else 0.55

    peer_ret20 = []
    for peer, pdf in prepped_all.items():
        if peer != sym and get_sector(peer) == sector and edate in pdf.index:
            v = pdf["Close"].pct_change(20).loc[edate]
            if pd.notna(v):
                peer_ret20.append(float(v))
    sector_mom = float(np.mean(peer_ret20)) if peer_ret20 else 0.0

    return {
        "rsi_at_entry":      float(row["rsi"]) if pd.notna(row["rsi"]) else 50.0,
        "wma_gap":           float(row["rsi"] - row["hm_wma"]) if pd.notna(row["hm_wma"]) else 0.0,
        "ema_gap":           float(row["rsi"] - row["hm_ema"]) if pd.notna(row["hm_ema"]) else 0.0,
        "atr_pct":           float(row.get("atr_pct", 0.02)) if pd.notna(row.get("atr_pct")) else 0.02,
        "vol_surge":         float(vol_surge),
        "dist_52w_high":     float((row["Close"] - high_52w) / high_52w) if high_52w else 0.0,
        "dist_ema50":        float((row["Close"] - ema50_val) / ema50_val) if pd.notna(ema50_val) and ema50_val else 0.0,
        "nifty_rsi":         float(nifty_row["nifty_rsi"]) if nifty_row is not None and pd.notna(nifty_row["nifty_rsi"]) else 50.0,
        "nifty_ret5":        float(nifty_row["nifty_ret5"]) if nifty_row is not None and pd.notna(nifty_row["nifty_ret5"]) else 0.0,
        "nifty_ret20":       float(nifty_row["nifty_ret20"]) if nifty_row is not None and pd.notna(nifty_row["nifty_ret20"]) else 0.0,
        "days_since_signal": float(min(days_gap, 365)),
        "prev_win":          float(last_win.get(sym, 0.5)),
        "sector_wr_hist":    sector_wr,
        "sector_momentum":   sector_mom,
    }


# ============================================================================
# PORTFOLIO ENGINE
# ============================================================================
def backtest(data: dict, index_df: pd.DataFrame, cfg: dict, ml_model=None):
    prepped = {}
    for sym, df in data.items():
        df = make_signals(compute_hm(df, cfg), cfg)
        df["entry_exec"] = df["entry"].shift(1, fill_value=False)
        df["exit_exec"]  = df["exit"].shift(1, fill_value=False)
        prepped[sym] = df

    idx        = index_df.copy()
    idx["sma"] = idx["Close"].rolling(cfg["REGIME_SMA"]).mean()
    idx["bull"]= idx["Close"] > idx["sma"]

    all_dates  = sorted(set().union(*[df.index for df in prepped.values()]))
    cash       = cfg["INITIAL_CAPITAL"]
    positions: dict[str, dict] = {}
    trades, equity = [], []
    cost_rate  = cfg["COST_BPS"] / 10_000.0
    min_hold   = cfg.get("MIN_HOLD_DAYS", 0)
    cooldown_until: dict[str, pd.Timestamp] = {}
    entry_log:  dict[str, list] = {}
    # ML state tracking
    ml_last_signal: dict[str, pd.Timestamp] = {}
    ml_last_win:    dict[str, int]           = {}
    use_ml      = ml_model is not None and cfg.get("USE_ML", False)
    ml_thresh   = cfg.get("ML_THRESHOLD", 0.45)
    ml_min_sig  = cfg.get("ML_MIN_SIGNALS", 5)
    ml_accepted = ml_rejected = 0
    from collections import defaultdict
    ml_sector_outcomes: dict[str, list] = defaultdict(list)  # sector -> [(date, outcome)]

    # Precompute total historical signal count per stock from the data itself.
    # This is the correct bypass check — uses all signal days in the dataset,
    # not just the entries the engine chose to take (entry_log is too sparse early on).
    ml_signal_counts: dict[str, int] = {}
    if use_ml:
        for sym, df in prepped.items():
            ml_signal_counts[sym] = int(df["entry"].sum())

    def regime_ok(d):
        if not cfg["USE_REGIME_FILTER"] or d not in idx.index:
            return True
        b = idx.at[d, "bull"]
        return bool(b) if pd.notna(b) else True

    def close_position(sym, exit_px, d, stopped: bool = False):
        nonlocal cash
        pos       = positions[sym]
        # Use total shares and blended cost for P&L (handles pyramided positions)
        total_shares = pos["shares"]
        gross        = total_shares * exit_px
        gross_pnl    = total_shares * (exit_px - pos["avg_px"])  # vs blended avg
        sell_cost    = gross * cost_rate
        hold         = (d - pos["entry_date"]).days
        tax = 0.0
        if cfg["APPLY_TAX"] and gross_pnl > 0:
            rate = cfg["STCG_RATE"] if hold <= 365 else cfg["LTCG_RATE"]
            tax  = gross_pnl * rate
        cash += gross - sell_cost - tax
        net_pnl = gross_pnl - pos["total_buy_cost"] - sell_cost - tax
        trades.append(dict(
            symbol=sym, entry=pos["entry_date"], exit=d, hold=hold,
            entry_px=pos["avg_px"], exit_px=exit_px,       # avg entry for pyramid trades
            shares=total_shares, gross_pnl=gross_pnl, net_pnl=net_pnl,
            ret_pct=100.0 * net_pnl / pos["cost_basis"],
            layers=pos.get("layers", 1),                    # how many entries this position had
            stopped=stopped,
        ))
        if stopped:
            cd = cfg.get("STOP_COOLDOWN_DAYS", 0)
            if cd > 0:
                cooldown_until[sym] = d + pd.Timedelta(days=cd)
        ml_last_win[sym] = 1 if net_pnl > 0 else 0
        ml_sector_outcomes[get_sector(sym)].append((d, 1 if net_pnl > 0 else 0))
        del positions[sym]

    for d in all_dates:
        # 1. EXITS
        for sym in list(positions.keys()):
            df  = prepped[sym]
            if d not in df.index:
                continue
            pos = positions[sym]
            row = df.loc[d]
            hold_days = (d - pos["entry_date"]).days
            exit_px   = None

            # Hard stop: fires immediately, ignores MIN_HOLD_DAYS
            hard_stop = cfg.get("HARD_STOP_PCT")
            if hard_stop and exit_px is None:
                stop_px = pos["stop_px"]           # blended stop (updated on each pyramid)
                if row["Low"] <= stop_px:
                    exit_px = min(row["Open"], stop_px)
                    close_position(sym, exit_px, d, stopped=True)
                    continue

            # ATR trailing stop (also ignores MIN_HOLD_DAYS)
            if exit_px is None and cfg["EXIT_MODE"] == "atr_trail":
                pos["peak"] = max(pos["peak"], row["Close"])
                cur_atr = row["atr"] if pd.notna(row["atr"]) else pos["atr_at_entry"]
                stop = pos["peak"] - cfg["ATR_MULT"] * cur_atr
                if row["Low"] <= stop:
                    exit_px = min(row["Open"], stop)

            # Indicator exit only fires after MIN_HOLD_DAYS
            if exit_px is None and hold_days >= min_hold and bool(row["exit_exec"]):
                exit_px = row["Open"]

            if exit_px is not None:
                close_position(sym, exit_px, d)

        # 1b. PYRAMID — add to existing winning positions on fresh re-signal
        pyr_max  = cfg.get("PYRAMID_MAX", 0)
        pyr_size = cfg.get("PYRAMID_SIZE", 0.5)
        if pyr_max > 0 and regime_ok(d):
            for sym in list(positions.keys()):
                pos = positions[sym]
                if pos.get("layers", 1) >= pyr_max + 1:
                    continue                     # max layers reached
                df  = prepped[sym]
                if d not in df.index:
                    continue
                row = df.loc[d]
                # Only add if: fresh entry signal AND current price > avg entry (winning)
                if not (bool(row["entry_exec"]) and row["Open"] > pos["avg_px"]):
                    continue
                # Size add-on as fraction of original slot alloc
                add_alloc  = pos["slot_alloc"] * pyr_size
                add_shares = int(add_alloc // row["Open"])
                if add_shares <= 0 or add_alloc > cash:
                    continue
                add_cost   = add_shares * row["Open"]
                buy_cost   = add_cost * cost_rate
                cash      -= add_cost + buy_cost
                # Update blended position — weighted avg price
                total_shares = pos["shares"] + add_shares
                pos["avg_px"]        = (pos["avg_px"] * pos["shares"] +
                                        row["Open"] * add_shares) / total_shares
                pos["shares"]        = total_shares
                pos["cost_basis"]   += add_cost
                pos["total_buy_cost"] += buy_cost
                pos["layers"]        = pos.get("layers", 1) + 1
                # Move stop up: protect blended cost with same stop %
                if cfg.get("HARD_STOP_PCT"):
                    pos["stop_px"] = pos["avg_px"] * (1.0 - cfg["HARD_STOP_PCT"])
                print(f"  PYR {sym}: layer {pos['layers']} "
                      f"+{add_shares}@{row['Open']:.1f} "
                      f"avg={pos['avg_px']:.1f} stop={pos['stop_px']:.1f}")

        # 2. NEW STOCK ENTRIES
        free = cfg["MAX_POSITIONS"] - len(positions)
        if free > 0 and regime_ok(d):
            max_tpw  = cfg.get("MAX_TRADES_PER_STOCK", 0)
            win_days = cfg.get("TRADE_WINDOW_DAYS", 90)
            cands = []
            for sym, df in prepped.items():
                if sym in positions or d not in df.index:
                    continue
                # Cooldown check: skip if recently stopped out
                if sym in cooldown_until and d < cooldown_until[sym]:
                    continue
                # Trade-count gate: skip if hit max entries in rolling window
                if max_tpw > 0 and sym in entry_log:
                    window_start = d - pd.Timedelta(days=win_days)
                    recent = [e for e in entry_log[sym] if e >= window_start]
                    if len(recent) >= max_tpw:
                        continue
                row = df.loc[d]
                if bool(row["entry_exec"]) and row["Open"] > 0 and pd.notna(row["rsi"]):
                    cands.append((sym, row))
            cands.sort(key=lambda kv: kv[1][cfg["RANK_BY"]], reverse=True)

            # ML filter: score each candidate and reject below threshold
            if use_ml and cands:
                filtered = []
                for sym, row in cands:
                    feats = build_live_features(
                        sym, row, prepped[sym], d, index_df,
                        cfg, ml_last_signal, ml_last_win,
                        ml_sector_outcomes, prepped
                    )
                    # Bypass: stocks with few total signals in dataset auto-pass.
                    # Use precomputed count from data, not entry_log (which is
                    # too sparse early in the backtest and causes all stocks to bypass).
                    if ml_signal_counts.get(sym, 0) < ml_min_sig:
                        filtered.append((sym, row, 1.0))  # auto-pass
                        ml_accepted += 1
                        continue
                    X_row = pd.DataFrame([feats])[FEATURE_COLS].fillna(0)
                    prob  = float(ml_model.predict_proba(X_row)[0, 1])
                    if prob >= ml_thresh:
                        filtered.append((sym, row, prob))
                        ml_accepted += 1
                    else:
                        ml_rejected += 1
                # Re-sort by ML probability (highest confidence first)
                filtered.sort(key=lambda x: x[2], reverse=True)
                cands = [(s, r) for s, r, _ in filtered]

            # Track ALL signal days for ML feature building (not just accepted entries)
            # This ensures ml_last_signal is accurate for prev_win / days_since features
            for sym, row in cands:
                ml_last_signal[sym] = d
            sizing = cfg.get("SIZING_MODE", "equal")
            n_entering = min(free, len(cands))

            if n_entering > 0 and sizing in ("vol_scale", "atr_pct"):
                raw_risks = []
                for sym, row in cands[:free]:
                    if sizing == "atr_pct":
                        ap = row["atr_pct"] if pd.notna(row.get("atr_pct")) else 0.02
                        raw_risks.append(max(ap, 1e-6))
                    else:  # vol_scale
                        rv = row["rvol"] if pd.notna(row.get("rvol")) else 0.02
                        raw_risks.append(max(rv, 1e-6))
                inv_risks  = [1.0 / r for r in raw_risks]
                total_inv  = sum(inv_risks)
                vol_weights = [iv / total_inv for iv in inv_risks]
            else:
                n_safe = max(1, n_entering)
                vol_weights = [1.0 / n_safe] * n_safe

            total_capital = cash + sum(
                pos["shares"] * (prepped[s].at[d, "Close"]
                                 if d in prepped[s].index else pos["entry_px"])
                for s, pos in positions.items()
            )

            for i, (sym, row) in enumerate(cands[:free]):
                if sizing == "equal":
                    remaining = cfg["MAX_POSITIONS"] - len(positions)
                    alloc = cash / max(1, remaining)

                elif sizing in ("vol_scale", "atr_pct"):
                    wi = vol_weights[i] if i < len(vol_weights) else 1.0 / free
                    alloc = total_capital * wi

                elif sizing == "risk_parity":
                    cur_atr = row["atr"] if pd.notna(row["atr"]) else row["Open"] * 0.02
                    risk_rs = total_capital * cfg.get("RISK_PCT", 0.02)
                    alloc   = risk_rs / (cur_atr / row["Open"]) if cur_atr > 0 else cash / free
                    alloc   = min(alloc, cash)

                else:
                    alloc = cash / max(1, cfg["MAX_POSITIONS"] - len(positions))

                shares = int(alloc // row["Open"])
                if shares <= 0:
                    continue
                cost_basis = shares * row["Open"]
                if cost_basis > cash:
                    shares     = int(cash // row["Open"])
                    cost_basis = shares * row["Open"]
                if shares <= 0:
                    continue
                buy_cost = cost_basis * cost_rate
                cash -= cost_basis + buy_cost
                positions[sym] = dict(
                    entry_date=d, entry_px=row["Open"], avg_px=row["Open"],
                    shares=shares, cost_basis=cost_basis,
                    buy_cost=buy_cost, total_buy_cost=buy_cost,
                    slot_alloc=alloc,
                    stop_px=row["Open"] * (1.0 - cfg.get("HARD_STOP_PCT", 0.08)),
                    peak=row["Close"], atr_at_entry=row["atr"],
                    layers=1,
                )
                # Log entry for trade-count gate
                entry_log.setdefault(sym, []).append(d)

        # 3. MTM
        mtm = cash
        for sym, pos in positions.items():
            df = prepped[sym]
            px = df.at[d,"Close"] if d in df.index else pos["entry_px"]
            mtm += pos["shares"] * px
        equity.append((d, mtm))

    eq = pd.Series(dict(equity)).sort_index()
    if use_ml and (ml_accepted + ml_rejected) > 0:
        print(f"\n  ML filter: accepted={ml_accepted} rejected={ml_rejected} "
              f"({100*ml_rejected/(ml_accepted+ml_rejected):.0f}% filtered)")
    return pd.DataFrame(trades), eq, idx


# ============================================================================
# REPORTING
# ============================================================================
def report(trades: pd.DataFrame, eq: pd.Series, idx: pd.DataFrame, cfg: dict,
           verbose: bool = True) -> dict:
    sep = "=" * 70
    print("\n" + sep)
    print(f"HILEGA MILEGA  entry={cfg['ENTRY_MODE']}  exit={cfg['EXIT_MODE']}"
          f"  min_hold={cfg.get('MIN_HOLD_DAYS',0)}d  regime={cfg['USE_REGIME_FILTER']}")
    print(f"               sizing={cfg.get('SIZING_MODE','equal')}"
          f"  hard_stop={cfg.get('HARD_STOP_PCT') or 'off'}"
          f"  ml={'ON thr='+str(cfg.get('ML_THRESHOLD',0.45)) if cfg.get('USE_ML') else 'off'}")
    print(sep)

    if eq.empty:
        print("No equity curve."); return {}

    yrs     = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    total   = eq.iloc[-1] / eq.iloc[0] - 1
    cagr    = (eq.iloc[-1] / eq.iloc[0]) ** (1/yrs) - 1
    rets    = eq.pct_change().dropna()
    std     = rets.std()
    sharpe  = float(np.sqrt(252) * rets.mean() / std) if std else 0.0
    ds      = rets[rets < 0].std()
    sortino = float(np.sqrt(252) * rets.mean() / ds) if ds else 0.0
    dd      = float((eq / eq.cummax() - 1).min())

    print(f"Period       : {eq.index[0].date()} → {eq.index[-1].date()} ({yrs:.1f}y)")
    print(f"Final equity : Rs{eq.iloc[-1]:>14,.0f}  (start Rs{eq.iloc[0]:,.0f})")
    print(f"Total return : {total*100:8.2f}%")
    print(f"CAGR         : {cagr*100:8.2f}%")
    print(f"Sharpe       : {sharpe:7.2f}")
    print(f"Sortino      : {sortino:7.2f}")
    print(f"Max drawdown : {dd*100:8.2f}%")

    bcommon = idx.reindex(eq.index).dropna(subset=["Close"])
    bcagr   = 0.0
    if len(bcommon) > 1:
        bcagr = (bcommon["Close"].iloc[-1] / bcommon["Close"].iloc[0]) ** (1/yrs) - 1
        print(f"Index CAGR   : {bcagr*100:8.2f}%    alpha {(cagr-bcagr)*100:+.2f}%")

    metrics = dict(cagr=cagr, sharpe=sharpe, sortino=sortino, dd=dd,
                   bcagr=bcagr, alpha=cagr-bcagr)

    if trades.empty:
        print("No trades closed."); return metrics

    wins   = trades[trades.net_pnl > 0]
    losses = trades[trades.net_pnl <= 0]
    pf = (wins.net_pnl.sum() / abs(losses.net_pnl.sum())
          if len(losses) and losses.net_pnl.sum() != 0 else float("inf"))

    print("-" * 70)
    print(f"Trades       : {len(trades)}")
    print(f"Win rate     : {100*len(wins)/len(trades):8.2f}%")
    print(f"Avg win      : {wins.ret_pct.mean():7.2f}%    Avg loss : {losses.ret_pct.mean():.2f}%")
    print(f"Expectancy   : {trades.ret_pct.mean():7.2f}% per trade")
    print(f"Profit factor: {pf:.2f}")
    print(f"Avg hold     : {trades.hold.mean():.0f} days  (median {trades.hold.median():.0f}d)")

    if verbose:
        sym_stats = (trades.groupby("symbol")
                     .agg(n=("net_pnl","count"),
                          net_pnl=("net_pnl","sum"),
                          wr=("net_pnl", lambda x: 100*(x>0).mean()),
                          avg_ret=("ret_pct","mean"),
                          avg_hold=("hold","mean"))
                     .sort_values("net_pnl", ascending=False))
        print(f"\nPer-symbol P&L  (top 20 and bottom 10)")
        print("-" * 70)
        print(f"{'Symbol':<15} {'Trades':>6} {'Net P&L':>11} {'WR%':>6} "
              f"{'AvgRet%':>8} {'AvgHold':>8}")
        to_show = pd.concat([sym_stats.head(20), sym_stats.tail(10)]).drop_duplicates()
        for sym, row in to_show.iterrows():
            flag = " ◄ DRAG" if row["net_pnl"] < -5000 else ""
            print(f"{sym:<15} {row['n']:>6.0f} {row['net_pnl']:>11,.0f} "
                  f"{row['wr']:>6.1f} {row['avg_ret']:>8.2f} "
                  f"{row['avg_hold']:>7.0f}d{flag}")

    print("=" * 70)
    return metrics


def run_sweep(data: dict, idx: pd.DataFrame, cfg: dict):
    entry_modes = ["stack_hold", "rsi_wma_cross", "rsi50_cross"]
    exit_modes  = ["wma_or_50",  "rsi50",         "rsi_wma",    "atr_trail"]
    hold_days   = [0, 5, 10, 15]
    results = []

    total = len(entry_modes) * len(exit_modes) * len(hold_days)
    done  = 0
    for em in entry_modes:
        for xm in exit_modes:
            for mh in hold_days:
                c = dict(cfg); c["ENTRY_MODE"]=em; c["EXIT_MODE"]=xm; c["MIN_HOLD_DAYS"]=mh
                t, eq, idx2 = backtest(data, idx, c)
                done += 1
                print(f"  sweep {done}/{total}: {em} + {xm} + hold≥{mh}d …", end="\r")
                if eq.empty or len(t) == 0:
                    continue
                yrs  = max((eq.index[-1]-eq.index[0]).days/365.25, 1e-9)
                cagr = (eq.iloc[-1]/eq.iloc[0])**(1/yrs) - 1
                rets = eq.pct_change().dropna()
                std  = rets.std()
                sh   = float(np.sqrt(252)*rets.mean()/std) if std else 0.0
                dd   = float((eq/eq.cummax()-1).min())
                wins = t[t.net_pnl > 0]
                results.append(dict(entry=em, exit=xm, min_hold=mh,
                                    cagr=cagr*100, sharpe=sh, dd=dd*100,
                                    trades=len(t), wr=100*len(wins)/len(t),
                                    avg_hold=t.hold.mean()))

    if not results:
        print("\nNo results."); return

    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    print("\n" + "=" * 95)
    print("SWEEP — ranked by Sharpe")
    print("=" * 95)
    print(f"{'Entry':<16} {'Exit':<12} {'Hold≥':>5} {'CAGR%':>7} {'Sharpe':>7} "
          f"{'MaxDD%':>8} {'Trades':>7} {'WR%':>6} {'AvgHold':>8}")
    print("-" * 95)
    for _, row in df.iterrows():
        print(f"{row.entry:<16} {row.exit:<12} {row.min_hold:>4}d "
              f"{row.cagr:>7.2f} {row.sharpe:>7.2f} {row.dd:>8.2f} "
              f"{row['trades']:>7.0f} {row.wr:>6.1f} {row.avg_hold:>7.0f}d")
    print("=" * 95)


def run_sizing_sweep(data: dict, idx: pd.DataFrame, cfg: dict):
    """Compare sizing modes and hard-stop / cooldown / trade-gate settings."""
    sizing_modes = ["equal", "atr_pct", "vol_scale", "risk_parity"]
    hard_stops   = [None, 0.06, 0.08, 0.10, 0.15]
    results = []
    total = len(sizing_modes) * len(hard_stops)
    done  = 0
    for sm in sizing_modes:
        for hs in hard_stops:
            c = dict(cfg); c["SIZING_MODE"] = sm; c["HARD_STOP_PCT"] = hs
            t, eq, idx2 = backtest(data, idx, c)
            done += 1
            hs_label = f"{int(hs*100)}%" if hs else "off"
            print(f"  sizing sweep {done}/{total}: {sm} stop={hs_label} …", end="\r")
            if eq.empty or len(t) == 0:
                continue
            yrs  = max((eq.index[-1]-eq.index[0]).days/365.25, 1e-9)
            cagr = (eq.iloc[-1]/eq.iloc[0])**(1/yrs) - 1
            rets = eq.pct_change().dropna()
            std  = rets.std()
            sh   = float(np.sqrt(252)*rets.mean()/std) if std else 0.0
            dd   = float((eq/eq.cummax()-1).min())
            wins = t[t.net_pnl > 0]
            results.append(dict(sizing=sm, hard_stop=hs_label,
                                cagr=cagr*100, sharpe=sh, dd=dd*100,
                                trades=len(t), wr=100*len(wins)/len(t),
                                avg_hold=t.hold.mean()))

    if not results:
        print("\nNo results."); return
    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    print("\n" + "=" * 82)
    print(f"SIZING SWEEP  entry={cfg['ENTRY_MODE']} exit={cfg['EXIT_MODE']} "
          f"min_hold={cfg.get('MIN_HOLD_DAYS',0)}d — ranked by Sharpe")
    print("=" * 82)
    print(f"{'Sizing':<14} {'Stop':>6} {'CAGR%':>7} {'Sharpe':>7} "
          f"{'MaxDD%':>8} {'Trades':>7} {'WR%':>6} {'AvgHold':>8}")
    print("-" * 82)
    for _, row in df.iterrows():
        print(f"{row.sizing:<14} {row.hard_stop:>6} {row.cagr:>7.2f} {row.sharpe:>7.2f} "
              f"{row.dd:>8.2f} {row['trades']:>7.0f} {row.wr:>6.1f} {row.avg_hold:>7.0f}d")
    print("=" * 82)


def run_vwap_sweep(data: dict, idx: pd.DataFrame, cfg: dict):
    """
    Systematic comparison of:
      - All exit modes (including new VWAP modes)
      - With and without VWAP entry filter
      - Both VWAP types (weekly vs anchored_52w)
    Ranked by Sharpe. Run this once to find the best exit config.
    """
    exit_modes  = [
        "wma_or_50",        # baseline
        "rsi50_only",       # looser, holds longer
        "rsi_wma",          # WMA-only exit
        "atr_trail",        # trailing stop
        "vwap_break",       # exit on VWAP cross
        "wma50_and_vwap",   # hybrid tight
        "rsi50_and_vwap",   # hybrid medium
    ]
    vwap_entries = [False, True]
    vwap_types   = ["weekly", "anchored_52w"]

    results = []
    total   = len(exit_modes) * len(vwap_entries) * len(vwap_types)
    done    = 0

    for vt in vwap_types:
        for ve in vwap_entries:
            for xm in exit_modes:
                c = dict(cfg)   # full copy of all CFG keys
                c["EXIT_MODE"]       = xm
                c["USE_VWAP_ENTRY"]  = ve
                c["VWAP_TYPE"]       = vt
                t, eq, _ = backtest(data, idx, c)
                done += 1
                print(f"  vwap sweep {done}/{total}: {xm} vwap_entry={ve} type={vt}", end="\r")
                if eq.empty or len(t) == 0:
                    continue
                yrs  = max((eq.index[-1]-eq.index[0]).days/365.25, 1e-9)
                cagr = (eq.iloc[-1]/eq.iloc[0])**(1/yrs) - 1
                rets = eq.pct_change().dropna()
                std  = rets.std()
                sh   = float(np.sqrt(252)*rets.mean()/std) if std else 0.0
                dd   = float((eq/eq.cummax()-1).min())
                wins = t[t.net_pnl > 0]
                results.append(dict(
                    exit=xm, vwap_entry=ve, vwap_type=vt,
                    cagr=cagr*100, sharpe=sh, dd=dd*100,
                    trades=len(t), wr=100*len(wins)/len(t),
                    avg_hold=t.hold.mean()
                ))

    if not results:
        print("\nNo results."); return

    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    print("\n" + "=" * 100)
    print("VWAP + EXIT MODE SWEEP — ranked by Sharpe")
    print("=" * 100)
    print(f"{'Exit mode':<18} {'VWAPentry':>9} {'VWAPtype':>12} {'CAGR%':>7} "
          f"{'Sharpe':>7} {'MaxDD%':>8} {'Trades':>7} {'WR%':>6} {'AvgHold':>8}")
    print("-" * 100)
    for _, row in df.iterrows():
        ve_str = "YES" if row.vwap_entry else "no"
        print(f"{row.exit:<18} {ve_str:>9} {row.vwap_type:>12} {row.cagr:>7.2f} "
              f"{row.sharpe:>7.2f} {row.dd:>8.2f} {row['trades']:>7.0f} "
              f"{row.wr:>6.1f} {row.avg_hold:>7.0f}d")
    print("=" * 100)
    best = df.iloc[0]
    print(f"\n★ Best: EXIT_MODE='{best.exit}' USE_VWAP_ENTRY={best.vwap_entry} "
          f"VWAP_TYPE='{best.vwap_type}' → CAGR {best.cagr:.2f}% Sharpe {best.sharpe:.2f}")


def run_pyramid_sweep(data: dict, idx: pd.DataFrame, cfg: dict):
    """
    Compare: no pyramid vs 1 add-on vs 2 add-ons,
    each with add-on sizes of 25%, 50%, 75% of original alloc.
    """
    configs = [
        dict(PYRAMID_MAX=0, PYRAMID_SIZE=0.0,  label="no pyramid (baseline)"),
        dict(PYRAMID_MAX=1, PYRAMID_SIZE=0.25, label="1 add @ 25%"),
        dict(PYRAMID_MAX=1, PYRAMID_SIZE=0.50, label="1 add @ 50%"),
        dict(PYRAMID_MAX=1, PYRAMID_SIZE=0.75, label="1 add @ 75%"),
        dict(PYRAMID_MAX=2, PYRAMID_SIZE=0.25, label="2 adds @ 25%"),
        dict(PYRAMID_MAX=2, PYRAMID_SIZE=0.50, label="2 adds @ 50%"),
    ]
    results = []
    for i, pc in enumerate(configs):
        c = dict(cfg)
        c["PYRAMID_MAX"]  = pc["PYRAMID_MAX"]
        c["PYRAMID_SIZE"] = pc["PYRAMID_SIZE"]
        print(f"  pyramid sweep {i+1}/{len(configs)}: {pc['label']} …", end="\r")
        t, eq, _ = backtest(data, idx, c)
        if eq.empty or len(t) == 0:
            continue
        yrs  = max((eq.index[-1]-eq.index[0]).days/365.25, 1e-9)
        cagr = (eq.iloc[-1]/eq.iloc[0])**(1/yrs) - 1
        rets = eq.pct_change().dropna()
        std  = rets.std()
        sh   = float(np.sqrt(252)*rets.mean()/std) if std else 0.0
        dd   = float((eq/eq.cummax()-1).min())
        wins = t[t.net_pnl > 0]
        # Avg layers per trade
        avg_layers = t.get("layers", pd.Series([1]*len(t))).mean() if "layers" in t.columns else 1.0
        results.append(dict(
            label=pc["label"], cagr=cagr*100, sharpe=sh, dd=dd*100,
            trades=len(t), wr=100*len(wins)/len(t),
            avg_hold=t.hold.mean(), avg_layers=avg_layers,
        ))

    if not results:
        print("\nNo results."); return
    df = pd.DataFrame(results)
    print("\n" + "=" * 90)
    print("PYRAMID SWEEP — no pyramid is the baseline, everything else is vs that")
    print("=" * 90)
    print(f"{'Config':<24} {'CAGR%':>7} {'Sharpe':>7} {'MaxDD%':>8} "
          f"{'Trades':>7} {'WR%':>6} {'AvgHold':>8} {'AvgLayers':>10}")
    print("-" * 90)
    base_cagr   = df.iloc[0]["cagr"]
    base_sharpe = df.iloc[0]["sharpe"]
    for _, row in df.iterrows():
        delta_c = row.cagr - base_cagr
        delta_s = row.sharpe - base_sharpe
        flag = f"  ▲ CAGR {delta_c:+.2f}% Sharpe {delta_s:+.2f}" if delta_c != 0 else ""
        print(f"{row.label:<24} {row.cagr:>7.2f} {row.sharpe:>7.2f} {row.dd:>8.2f} "
              f"{row['trades']:>7.0f} {row.wr:>6.1f} {row.avg_hold:>7.0f}d "
              f"{row.avg_layers:>9.1f}x{flag}")
    print("=" * 90)
    best = df.sort_values("sharpe", ascending=False).iloc[0]
    print(f"\n★ Best Sharpe: {best.label} → CAGR {best.cagr:.2f}% Sharpe {best.sharpe:.2f}")


# ============================================================================
# MAIN
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="Hilega Milega Backtest")
    ap.add_argument("--synthetic",   action="store_true")
    ap.add_argument("--sweep",       action="store_true",
                    help="all entry×exit×hold_days combos ranked")
    ap.add_argument("--sizingsweep", action="store_true",
                    help="compare sizing modes and hard-stop levels")
    ap.add_argument("--vwapsweep",   action="store_true",
                    help="compare all exit modes × VWAP entry filter × VWAP type")
    ap.add_argument("--pyramid",     action="store_true",
                    help="compare no-pyramid vs 1-add vs 2-add pyramiding")
    ap.add_argument("--nifty200",    action="store_true",
                    help="use Nifty 200 universe from nifty200_cache.csv")
    ap.add_argument("--stocks",      nargs="+", default=None,
                    help="focused backtest on specific stocks only, e.g. --stocks CGPOWER GRSE IIFL "
                         "(seconds not minutes — great for checking individual positions)")
    ap.add_argument("--start",       type=str, default=None,
                    help="override start date, e.g. --start 2022-01-01")
    ap.add_argument("--capital",     type=float, default=None,
                    help="override starting capital, e.g. --capital 100000")
    ap.add_argument("--train",       action="store_true",
                    help="train ML signal classifier on full dirty universe "
                         "and save to ML_MODEL_PATH")
    ap.add_argument("--ml",          action="store_true",
                    help="load saved ML model and apply as signal filter")
    ap.add_argument("--threshold",   type=float, default=None,
                    help="override ML_THRESHOLD (e.g. --threshold 0.50)")
    args = ap.parse_args()
    cfg  = dict(CFG)  # copy so we can mutate

    if args.threshold is not None:
        cfg["ML_THRESHOLD"] = args.threshold
    if args.start is not None:
        cfg["START"] = args.start
    if args.capital is not None:
        cfg["INITIAL_CAPITAL"] = args.capital

    # ── DATA LOADING ────────────────────────────────────────────────────────
    if args.synthetic:
        print("[synthetic] generating GBM OHLCV (first 30 symbols) …")
        data, idx = make_synthetic(cfg)
        train_data = data
    elif args.stocks:
        # Focused single/few-stock backtest — fast (seconds not minutes)
        syms = [s.upper() for s in args.stocks]
        print(f"[stocks] focused backtest: {syms}")
        data, idx = load_yf(cfg, symbols_override=syms)
        train_data = data
    elif args.train:
        # Training uses the full dirty universe = SYMBOLS + ML_TRAINING_EXTRA
        extra = cfg.get("ML_TRAINING_EXTRA", [])
        all_syms = list(dict.fromkeys(cfg["SYMBOLS"] + extra))  # preserve order, dedup
        print(f"[train] downloading {len(all_syms)} symbols (clean + dirty universe) …")
        data, idx = load_yf(cfg, symbols_override=all_syms)
        train_data = data
    elif args.nifty200:
        syms = load_nifty200_universe(cfg)
        print(f"[nifty200] downloading {len(syms)} symbols …")
        data, idx = load_yf(cfg, symbols_override=syms)
        train_data = data
    else:
        exclude = cfg.get("EXCLUDE_SYMBOLS", set())
        active  = [s for s in cfg["SYMBOLS"] if s not in exclude]
        print(f"[live] downloading {len(active)} symbols from yfinance "
              f"({len(exclude)} excluded) …")
        data, idx = load_yf(cfg)
        train_data = data
    print(f"Loaded {len(data)} symbols\n")

    # ── TRAIN MODE ──────────────────────────────────────────────────────────
    if args.train:
        print("=" * 60)
        print("PHASE 1 — Run base backtest on full dirty universe to collect signals")
        print("=" * 60)
        # Run without ML to get all signal/trade data
        base_cfg = dict(cfg); base_cfg["USE_ML"] = False
        trades, eq, idx2 = backtest(train_data, idx, base_cfg)
        print(f"Base backtest: {len(trades)} trades collected across full universe")

        print("\n" + "=" * 60)
        print("PHASE 2 — Extract features from every signal day")
        print("=" * 60)
        # Need prepped frames for feature extraction
        prepped_for_feat = {}
        for sym, df in train_data.items():
            df2 = make_signals(compute_hm(df, cfg), cfg)
            df2["entry_exec"] = df2["entry"].shift(1, fill_value=False)
            prepped_for_feat[sym] = df2

        feature_df = build_feature_rows(prepped_for_feat, trades, idx, cfg)
        print(f"Feature rows built: {len(feature_df)}")
        if not feature_df.empty:
            feature_df.to_csv("hm_training_features.csv", index=False)
            print("  Features saved → hm_training_features.csv")

        print("\n" + "=" * 60)
        print("PHASE 3 — Train classifier (walk-forward split)")
        print("=" * 60)
        train_end = pd.Timestamp(cfg.get("ML_TRAIN_END", "2022-12-31"))
        train_feat = feature_df[feature_df["entry_date"] <= train_end]
        print(f"  Training on {len(train_feat)} signal days (up to {train_end.date()})")
        model = train_ml_model(train_feat, cfg)

        if model is not None:
            print("\n" + "=" * 60)
            print("PHASE 4 — Walk-forward evaluation on held-out test set")
            print("=" * 60)
            evaluate_ml_model(model, feature_df, cfg)
            save_model(model, cfg.get("ML_MODEL_PATH", "hm_signal_clf.pkl"))

            print("\n" + "=" * 60)
            print("PHASE 5 — Compare base vs ML-filtered backtest (test period only)")
            print("=" * 60)
            test_start = train_end + pd.Timedelta(days=1)
            print(f"  Test period: {test_start.date()} → end of data")
            print(f"  (Full data used in engine for warm-up; only test-period trades reported)\n")

            def filter_to_test(trades_df, eq_series, start):
                """Restrict trades and equity curve to the test period."""
                t = trades_df[pd.to_datetime(trades_df["entry"]) >= start].copy()
                e = eq_series[eq_series.index >= start].copy()
                if not e.empty:
                    # Re-base equity to 100k at test period start
                    scale = cfg["INITIAL_CAPITAL"] / e.iloc[0]
                    e = e * scale
                return t, e

            # Base: full data, no ML
            base_cfg2 = dict(cfg); base_cfg2["USE_ML"] = False
            t_base_full, eq_base_full, _ = backtest(train_data, idx, base_cfg2)
            t_base, eq_base = filter_to_test(t_base_full, eq_base_full, test_start)
            print("Base (no ML) — test period only:")
            report(t_base, eq_base, idx[idx.index >= test_start], base_cfg2, verbose=False)

            # ML filtered: full data, ML active
            ml_cfg = dict(cfg); ml_cfg["USE_ML"] = True
            t_ml_full, eq_ml_full, _ = backtest(train_data, idx, ml_cfg, ml_model=model)
            t_ml, eq_ml = filter_to_test(t_ml_full, eq_ml_full, test_start)
            print("\nML-filtered — test period only:")
            report(t_ml, eq_ml, idx[idx.index >= test_start], ml_cfg, verbose=False)

            # Summary delta
            if not t_base.empty and not t_ml.empty:
                def metrics(t, eq):
                    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
                    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/yrs) - 1
                    wr = 100 * (t.net_pnl > 0).mean()
                    return cagr*100, wr, len(t)
                b_cagr, b_wr, b_n = metrics(t_base, eq_base)
                m_cagr, m_wr, m_n = metrics(t_ml, eq_ml)
                print(f"\n  Delta: CAGR {m_cagr-b_cagr:+.2f}%  WR {m_wr-b_wr:+.1f}%  Trades {m_n-b_n:+d}")
        return

    # ── ML LOAD ─────────────────────────────────────────────────────────────
    ml_model = None
    if args.ml:
        cfg["USE_ML"] = True
        ml_model = load_model(cfg.get("ML_MODEL_PATH", "hm_signal_clf.pkl"))
        if ml_model is None:
            print("  ! No saved model found. Run --train first.")
            return
        print(f"  ML model loaded from {cfg.get('ML_MODEL_PATH','hm_signal_clf.pkl')}"
              f"  threshold={cfg['ML_THRESHOLD']}")

    # ── STANDARD RUN ────────────────────────────────────────────────────────
    if args.sweep:
        run_sweep(data, idx, cfg)
    elif args.sizingsweep:
        run_sizing_sweep(data, idx, cfg)
    elif args.vwapsweep:
        run_vwap_sweep(data, idx, cfg)
    elif args.pyramid:
        run_pyramid_sweep(data, idx, cfg)
    else:
        trades, eq, idx2 = backtest(data, idx, cfg, ml_model=ml_model)
        report(trades, eq, idx2, cfg, verbose=True)
        if not trades.empty:
            out = "hm_trades.csv"
            # Add model column for dashboard compatibility
            trades["model"] = "HM"
            trades.to_csv(out, index=False)
            print(f"\nTrade log → {out}")


if __name__ == "__main__":
    main()

