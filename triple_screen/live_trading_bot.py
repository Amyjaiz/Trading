"""
TRIPLE SCREEN DEFENSE - CONTINUOUS LIVE BOT v3
Merged: Old bot style (runs anytime, emoji reports, full scan) +
        New bot power (real-time SL every 30s, live orders, token map, real margin)

RUN ANYTIME for a full report + signal scan (paper mode, no real orders):
    python live_trading_bot.py

RUN LIVE during market hours (9:15-3:25, real orders):
    python live_trading_bot.py --live

INSTALL:
    pip install smartapi-python pyotp yfinance pandas numpy requests
"""

import os, sys, math, time, logging, warnings, requests, json, pyotp, threading
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, time as dtime
from SmartApi import SmartConnect

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS — paste your values here
# ─────────────────────────────────────────────────────────────────────────────
API_KEY = "iAjEonEh"
CLIENT_ID = "M291016"
PIN = "1997"
TOTP_SEED = "BARMP6NWADQVUGL6ON76IOCTEA"

TELEGRAM_TOKEN   = "8830183227:AAHZMRD2q0_-eCaoCZPNI2rUEN030BmP6Zw"
TELEGRAM_CHAT_ID = "1417905325"

# ─────────────────────────────────────────────────────────────────────────────
# MODE
# --live  = real orders, runs all day, SL monitor active
# default = paper mode, runs once, full report, no real orders
# ─────────────────────────────────────────────────────────────────────────────
LIVE_MODE = "--live" in sys.argv

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
SIMULATED_CAPITAL     = 100_000.0  # used in paper mode for position sizing
RISK_PCT              = 0.03       # 3% risk per trade
ATR_MULT              = 2.5        # stop = entry - ATR14 x 2.5
MAX_POSITIONS         = 7          # max concurrent holdings
MAX_NEW_PER_RUN       = 3          # max new entries per day
MIN_PRICE             = 50.0       # skip stocks below Rs50

# ─────────────────────────────────────────────────────────────────────────────
# TOGGLEABLE FILTERS — adjust here without changing core strategy logic
# ─────────────────────────────────────────────────────────────────────────────

# Nifty regime filter — blocks all entries when Nifty < SMA (bear market)
# True  = respect backtest rule (recommended for live trading)
# False = scan and trade regardless of Nifty regime (paper mode / testing)
NIFTY_REGIME_FILTER   = True

# Nifty SMA period — 200 is the backtest default
# Shorter (100/150) = less restrictive, exits bear regime sooner
# Longer (200)      = more restrictive, matches original backtest exactly
# WARNING: changing this alters the strategy — re-backtest before going live
NIFTY_SMA_PERIOD      = 200

# ML signal filter — blocks low-probability signals
# True  = use ML classifier (recommended — AUC 0.6094, Sharpe 1.27)
# False = take every Triple Screen signal without ML filter
ML_FILTER_ENABLED     = True
ML_FILTER_THRESHOLD   = 0.45      # reject signals below this probability
SL_CHECK_INTERVAL     = 30         # live mode: check SL every 30 seconds
TRAIL_INTERVAL        = 300        # live mode: update trailing stop every 5 min

# Verbose per-stock screen breakdown in scan logs (S1/S2/S3 pass/fail)
VERBOSE_SCAN          = False

# Market timing IST
MARKET_OPEN   = dtime(9, 15)
SCAN_TIME     = dtime(9, 20)
MARKET_CLOSE  = dtime(15, 25)

# Files
MEMORY_FILE = "open_positions.csv"
LOG_FILE    = "bot.log"
TOKEN_FILE  = "angel_tokens.json"

# Dashboard integration — re-read on every scan so Universe page add/remove
# changes take effect without a bot restart (same pattern as hm_live_bot.py)
CUSTOM_UNIVERSE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "custom_universe.json"
)

# ─────────────────────────────────────────────────────────────────────────────
# FULL STOCK UNIVERSE — same as your old bot
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# STOCK UNIVERSE — all 313 stocks from triple_screen_defense.py backtest
# Per-stock best trigger: proven from backtest CSV
# ─────────────────────────────────────────────────────────────────────────────
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

# Per-stock best trigger from backtest (115 BUY_STOP, 94 RSI_CROSS, 104 FORCE_IDX)
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

# Stocks with <5 historical signals — ML filter bypassed for these
# (too little data for model to calibrate correctly)
ML_BYPASS_STOCKS = {
    "NATCOPHARM","BOSCHLTD","RAMCOCEM","SUZLON","NAVINFLUOR","DBREALTY",
    "GOCOLORS","WHIRLPOOL","MOTHERSON","DELHIVERY","ECLERX","COFORGE",
    "COCHINSHIP","MAHLOG","HUDCO","TRENT","PRSMJOHNSN","SUMICHEM",
    "HATSUN","BSOFT","RENUKA","CENTRALBK","GODFRYPHLP","SAPPHIRE",
}

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD INTEGRATION — custom universe (add/remove) from the web dashboard
# ─────────────────────────────────────────────────────────────────────────────
def get_active_universe() -> list:
    """Re-reads dashboard/custom_universe.json on every call so stocks
    added/removed via the dashboard's Universe page take effect on the next
    scan — no bot restart needed. Falls back to the static STOCKS list if the
    file is missing or unreadable."""
    universe = list(STOCKS)
    try:
        with open(CUSTOM_UNIVERSE_FILE) as f:
            custom = json.load(f)
        section = custom.get("triple_screen", {})
        adds    = [s.upper() for s in section.get("add", [])]
        removes = {s.upper() for s in section.get("remove", [])}
        for s in adds:
            if s not in universe:
                universe.append(s)
        universe = [s for s in universe if s not in removes]
    except Exception as e:
        log.warning(f"Custom universe read failed: {e}")
    return universe

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL STATE (live mode thread safety)
# ─────────────────────────────────────────────────────────────────────────────
positions_lock = threading.Lock()
live_positions = {}   # {sym: {token, buy_price, qty, stop_loss, peak, entry_date}}
sold_today     = set()
_api_obj       = None
_api_lock      = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM — same style as your old bot (emoji + HTML)
# ─────────────────────────────────────────────────────────────────────────────
def tg(message: str, urgent: bool = False):
    """Print to console AND send to Telegram."""
    clean = (message.replace("<b>","").replace("</b>","")
                    .replace("<i>","").replace("</i>",""))
    print(clean)
    print("-" * 80)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.warning(f"Telegram error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────
def login() -> SmartConnect | None:
    print("Attempting login to Angel One...")
    try:
        obj  = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SEED).now()
        data = obj.generateSession(CLIENT_ID, PIN, totp)
        if data and data.get("status"):
            global _api_obj
            with _api_lock:
                _api_obj = obj
            print("Login Successful! Session Active.\n")
            return obj
        msg = (data or {}).get("message", "Unknown error")
        tg(f"CRITICAL: Login FAILED — {msg}", urgent=True)
        return None
    except Exception as e:
        tg(f"CRITICAL: Login exception — {e}", urgent=True)
        return None

def get_api() -> SmartConnect | None:
    global _api_obj
    with _api_lock:
        if _api_obj:
            return _api_obj
    return login()

def force_relogin():
    global _api_obj
    with _api_lock:
        _api_obj = None
    return login()

# ─────────────────────────────────────────────────────────────────────────────
# TOKEN MAP
# Tokens are only needed in LIVE MODE for real-time LTP and order placement.
# In PAPER MODE the bot runs fine without them — signals use yfinance data.
# ─────────────────────────────────────────────────────────────────────────────
def load_token_map() -> dict:
    """
    Downloads Angel One instrument master and builds {symbol: token} dict.
    Returns empty dict (not a fatal error) if download fails in paper mode.
    Tries two URLs in case one is down.
    """
    URLS = [
        "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/master/v1/getAllInstrument",
    ]

    # Check cache — but skip tiny/broken caches (hardcoded fallback has 47 symbols)
    if os.path.exists(TOKEN_FILE):
        age_days = (time.time() - os.path.getmtime(TOKEN_FILE)) / 86400
        if age_days < 7:
            try:
                with open(TOKEN_FILE) as f:
                    cached = json.load(f)
                if len(cached) > 100:   # only use cache if it has real data
                    log.info(f"Token map loaded from cache: {len(cached)} symbols.")
                    return cached
                else:
                    log.info(f"Cache has only {len(cached)} symbols — refreshing.")
            except Exception as e:
                log.warning(f"Cache read failed: {e}")

    log.info("Downloading instrument token map...")

    for url in URLS:
        try:
            r = requests.get(url, timeout=30, verify=True)
            r.raise_for_status()
            data = r.json()

            # Handle both list format and dict-wrapped format
            if isinstance(data, dict):
                data = data.get("data", [])

            # Debug: show first record to understand structure
            if data:
                sample = data[0]
                log.info(f"Token map sample record: {dict(list(sample.items())[:6])}")

            token_map = {}
            for inst in data:
                # New CDN format uses: token, symbol, name, expiry, strike, lotsize
                # Old CDN format uses: token, tradingsymbol, exch_seg, instrumenttype
                # Support both formats

                tok = str(inst.get("token", "")).strip()
                if not tok:
                    continue

                # Try new format first (symbol + name fields)
                sym_raw = (inst.get("symbol") or inst.get("tradingsymbol") or "").strip()
                name    = (inst.get("name") or "").strip()
                expiry  = (inst.get("expiry") or "").strip()
                strike  = str(inst.get("strike") or "0").strip()
                exch    = (inst.get("exch_seg") or "").strip()
                itype   = (inst.get("instrumenttype") or "").strip()

                # New format: equity if expiry="" and strike="0.000000" and no FUT/CE/PE
                is_new_format = "symbol" in inst and "exch_seg" not in inst
                if is_new_format:
                    if expiry != "":
                        continue  # has expiry = derivative
                    if strike not in ("0.000000", "0", "0.0", ""):
                        continue  # has strike = option
                    # Skip index tokens (Nifty, Sensex etc)
                    if any(w in name.upper() for w in ["NIFTY","SENSEX","BANK NIFTY",
                                                        "FINNIFTY","MIDCPNIFTY"]):
                        continue
                    # Skip if name looks like a derivative
                    if any(w in name.upper() for w in ["FUT","FUTURE","OPTION"]):
                        continue
                    sym = sym_raw.replace("-EQ","")
                    if sym:
                        token_map[sym] = tok

                # Old format: filter by exch_seg=NSE and instrumenttype
                else:
                    if exch != "NSE":
                        continue
                    if itype not in ("EQ", "", "-"):
                        continue
                    if sym_raw.endswith("CE") or sym_raw.endswith("PE"):
                        continue
                    if "FUT" in sym_raw:
                        continue
                    sym = sym_raw.replace("-EQ","")
                    if sym:
                        token_map[sym] = tok

            if token_map:
                with open(TOKEN_FILE, "w") as f:
                    json.dump(token_map, f)
                log.info(f"Token map saved: {len(token_map)} symbols.")
                return token_map
            else:
                log.warning(f"URL returned data but filter matched 0 symbols: {url}")
                # Show more sample data to debug
                log.warning(f"First 3 records: {data[:3]}")

        except Exception as e:
            log.warning(f"Token URL failed ({url}): {e}")
            continue

    # All URLs failed — build a minimal hardcoded token map for your watchlist
    # These are stable Angel One token IDs for major NSE stocks
    # Run once with internet to get full map; this is the emergency fallback
    log.warning("Building minimal hardcoded token map for watchlist stocks...")
    HARDCODED = {
        "HDFCBANK":"1333","ICICIBANK":"4963","AXISBANK":"5900","SBIN":"3045",
        "KOTAKBANK":"1922","INDUSINDBK":"5258","BAJFINANCE":"317","BAJAJFINSV":"16675",
        "HDFCLIFE":"467","SBILIFE":"21808","TCS":"11536","INFY":"1594","WIPRO":"3787",
        "HCLTECH":"7229","TECHM":"13538","RELIANCE":"2885","ONGC":"2475","BPCL":"526",
        "IOC":"1624","GAIL":"910","NTPC":"11630","POWERGRID":"14977","LT":"11483",
        "BEL":"383","HAL":"2303","BHEL":"438","SIEMENS":"19963","ABB":"13","TATASTEEL":"3506",
        "JSWSTEEL":"11723","HINDALCO":"1363","VEDL":"3063","COALINDIA":"20374","NMDC":"15332",
        "SUNPHARMA":"3351","DRREDDY":"881","CIPLA":"694","LUPIN":"10440","TITAN":"3506",
        "MARUTI":"10999","M&M":"519","HEROMOTOCO":"1348","BAJAJ-AUTO":"16669",
        "ADANIPORTS":"15083","ADANIGREEN":"25215","LT":"11483","IRCTC":"13611",
        "BHARTIARTL":"10604","HDFCBANK":"1333","ICICIBANK":"4963","SBIN":"3045",
        "INDUSINDBK":"5258","HCLTECH":"7229","IOC":"1624","TATASTEEL":"3506",
        "BPCL":"526","HINDALCO":"1363","WIPRO":"3787","COALINDIA":"20374",
        "VEDL":"3063","RELIANCE":"2885",
    }
    if HARDCODED:
        log.info(f"Using hardcoded fallback tokens: {len(HARDCODED)} symbols.")
        return HARDCODED

    # Return empty — paper mode will still work, live mode will warn per symbol
    log.warning(
        "Token map could not be downloaded. "
        "Paper mode will work normally (uses yfinance). "
        "Live mode will skip LTP and use yfinance prices instead."
    )
    return {}

# ─────────────────────────────────────────────────────────────────────────────
# LIVE PRICE
# ─────────────────────────────────────────────────────────────────────────────
def get_ltp(symbol: str, token: str) -> float | None:
    for _ in range(2):
        api = get_api()
        if not api:
            return None
        try:
            data = api.ltpData("NSE", symbol, token)
            if data and data.get("status"):
                return float(data["data"]["ltp"])
            msg = (data or {}).get("message","")
            if any(w in msg.lower() for w in ["token","session","auth","invalid"]):
                force_relogin()
                continue
            return None
        except Exception as e:
            log.error(f"LTP error {symbol}: {e}")
            return None
    return None

# ─────────────────────────────────────────────────────────────────────────────
# MARGIN
# ─────────────────────────────────────────────────────────────────────────────
def get_free_margin() -> float:
    api = get_api()
    if not api:
        return SIMULATED_CAPITAL
    try:
        data = api.rmsLimit()
        if data and data.get("status"):
            d = data.get("data", {})
            # Try all known Angel One margin field names
            best_val = 0.0
            for field in ["availablecash", "net", "availableintradaypayin",
                          "payin", "adhocmargin", "collateral"]:
                val = d.get(field, 0)
                try:
                    v = float(val or 0)
                    if v > best_val:
                        best_val = v
                except (TypeError, ValueError):
                    continue

            if best_val >= 100:
                log.info(f"Live margin from Angel One: Rs{best_val:,.2f}")
                return best_val
            else:
                # Account has very low balance — show clearly
                log.warning(
                    f"Angel One account balance is Rs{best_val:.2f}. "
                    f"Fund your account before live trading. "
                    f"Using SIMULATED_CAPITAL=Rs{SIMULATED_CAPITAL:,.0f} for paper mode."
                )
                return SIMULATED_CAPITAL
    except Exception as e:
        log.error(f"Margin error: {e}")
    return SIMULATED_CAPITAL

# ─────────────────────────────────────────────────────────────────────────────
# ORDER PLACEMENT
# ─────────────────────────────────────────────────────────────────────────────
def place_order(symbol: str, token: str, qty: int,
                side: str, price: float = 0.0) -> str | None:
    if not LIVE_MODE:
        fake = f"PAPER-{symbol}-{int(time.time())}"
        log.info(f"[PAPER] {side} {symbol} qty={qty} -> {fake}")
        return fake

    api = get_api()
    if not api:
        return None
    try:
        resp = api.placeOrder({
            "variety"        : "NORMAL",
            "tradingsymbol"  : symbol,
            "symboltoken"    : token,
            "transactiontype": side,
            "exchange"       : "NSE",
            "ordertype"      : "MARKET",
            "producttype"    : "DELIVERY",
            "duration"       : "DAY",
            "price"          : "0",
            "squareoff"      : "0",
            "stoploss"       : "0",
            "quantity"       : str(qty),
        })
        if resp and resp.get("status"):
            oid = resp["data"]["orderid"]
            log.info(f"Order OK: {symbol} {side} qty={qty} id={oid}")
            return oid
        msg = (resp or {}).get("message","Unknown")
        log.error(f"Order rejected {symbol}: {msg}")
        tg(f"ORDER REJECTED: {symbol} {side} qty={qty}\n{msg}", urgent=True)
        return None
    except Exception as e:
        log.error(f"placeOrder exception {symbol}: {e}")
        tg(f"ORDER EXCEPTION: {symbol} {side} — {e}", urgent=True)
        return None

def wait_fill(order_id: str, symbol: str) -> bool:
    if not LIVE_MODE:
        return True
    api = get_api()
    if not api:
        return False
    for _ in range(8):
        try:
            book = api.orderBook()
            if book and book.get("status"):
                for o in book["data"]:
                    if o.get("orderid") == order_id:
                        s = o.get("orderstatus","").upper()
                        if s == "COMPLETE":
                            return True
                        if s in ("REJECTED","CANCELLED"):
                            return False
        except Exception as e:
            log.warning(f"wait_fill: {e}")
        time.sleep(3)
    return False

# ─────────────────────────────────────────────────────────────────────────────
# POSITION MEMORY
# ─────────────────────────────────────────────────────────────────────────────
COLS = ["Symbol","Token","BuyPrice","Qty","StopLoss","EntryDate","OrderId"]

def load_positions() -> dict:
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        df = pd.read_csv(MEMORY_FILE)
        result = {}
        for _, row in df.iterrows():
            sym = str(row["Symbol"])
            result[sym] = {
                "token"      : str(row.get("Token","")),
                "buy_price"  : float(row["BuyPrice"]),
                "qty"        : int(row["Qty"]),
                "stop_loss"  : float(row["StopLoss"]),
                "entry_date" : str(row.get("EntryDate","")),
                "order_id"   : str(row.get("OrderId","")),
                "peak"       : float(row["BuyPrice"]),
            }
        return result
    except Exception as e:
        log.error(f"Load positions error: {e}")
        return {}

def save_positions():
    try:
        rows = []
        with positions_lock:
            for sym, p in live_positions.items():
                rows.append({
                    "Symbol"   : sym,       "Token"     : p.get("token",""),
                    "BuyPrice" : p["buy_price"], "Qty"   : p["qty"],
                    "StopLoss" : p["stop_loss"], "EntryDate": p.get("entry_date",""),
                    "OrderId"  : p.get("order_id",""),
                })
        pd.DataFrame(rows, columns=COLS).to_csv(MEMORY_FILE, index=False)
    except Exception as e:
        log.error(f"Save positions error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────
def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def _rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(span=p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=p, adjust=False).mean()
    return 100 - 100/(1 + g/(l+1e-10))

def _fi(close, vol, p=13):
    return (close.diff() * vol).ewm(span=p, adjust=False).mean()

def _atr(high, low, close, p=14):
    tr = pd.concat([high-low,
                    (high-close.shift()).abs(),
                    (low-close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def check_signals(df: pd.DataFrame, token_map: dict, sym: str,
                  nifty_bull: bool = True) -> dict | None:
    """
    Exact match to triple_screen_defense.py backtest:
    Screen 1: close > EMA50
    Screen 2: RSI[2] < 30 YESTERDAY  (shift(1) in backtest)
    Screen 3: per-stock proven trigger from BEST_TRIGGER dict only
    Nifty:    if nifty_bull=False, block all new entries
    """
    try:
        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        vol    = df["Volume"]

        ema50  = _ema(close, 50)
        ema20  = _ema(close, 20)
        rsi2   = _rsi(close, 2)
        rsi14  = _rsi(close, 14)
        fi13   = _fi(close, vol, 13)
        atr14  = _atr(high, low, close, 14)
        atr63  = atr14.rolling(63).mean()
        vol_sma20 = vol.rolling(20).mean()
        sma200 = close.rolling(200).mean()
        high52 = high.rolling(252).max()
        low52  = low.rolling(252).min()

        c0      = float(close.iloc[-1])
        h1      = float(high.iloc[-2])
        rsi2_p  = float(rsi2.iloc[-2])   # yesterday RSI[2] — matches shift(1)
        rsi14_0 = float(rsi14.iloc[-1])
        rsi14_1 = float(rsi14.iloc[-2])
        fi_0    = float(fi13.iloc[-1])
        fi_1    = float(fi13.iloc[-2])
        ema50_0 = float(ema50.iloc[-1])
        ema20_0 = float(ema20.iloc[-1])
        atr_0   = float(atr14.iloc[-1])
        atr63_0 = float(atr63.iloc[-1]) if not np.isnan(float(atr63.iloc[-1])) else atr_0
        vol_0   = float(vol.iloc[-1])
        vsma_0  = float(vol_sma20.iloc[-1]) if not np.isnan(float(vol_sma20.iloc[-1])) else vol_0
        sma200_0= float(sma200.iloc[-1]) if not np.isnan(float(sma200.iloc[-1])) else c0
        h52_0   = float(high52.iloc[-1]) if not np.isnan(float(high52.iloc[-1])) else c0
        l52_0   = float(low52.iloc[-1])  if not np.isnan(float(low52.iloc[-1]))  else c0

        if np.isnan(atr_0) or atr_0 <= 0:
            atr_0 = c0 * 0.02

        s1 = c0 > ema50_0    # Screen 1: above EMA50
        s2 = rsi2_p < 30     # Screen 2: yesterday pullback (shift(1))

        # Screen 3: ONLY the stock's proven trigger from backtest
        trigger = BEST_TRIGGER.get(sym, "BUY_STOP")
        if trigger == "BUY_STOP":
            s3 = c0 > h1
        elif trigger == "RSI_CROSS":
            s3 = (rsi14_0 > 40) and (rsi14_1 <= 40)
        else:  # FORCE_IDX
            s3 = (fi_0 > 0) and (fi_1 <= 0)

        # Nifty bear block — matches backtest nifty_bull_regime
        signal = s1 and s2 and s3 and nifty_bull

        return {
            "signal"     : signal,
            "trigger"    : trigger,
            "price"      : c0,
            "atr"        : atr_0,
            "stop_loss"  : round(c0 - ATR_MULT * atr_0, 2),
            "s1"         : s1, "s2": s2, "s3": s3,
            # ML feature values — computed here so no extra download needed
            "ml_feats"   : {
                "pullback_depth"   : rsi2_p,
                "dist_ema50"       : (c0 - ema50_0) / (ema50_0 + 1e-10),
                "dist_ema20"       : (c0 - ema20_0) / (ema20_0 + 1e-10),
                "rsi14"            : rsi14_0,
                "atr_ratio"        : atr_0 / (atr63_0 + 1e-10),
                "atr_pct"          : atr_0 / (c0 + 1e-10),
                "vol_surge"        : vol_0 / (vsma_0 + 1e-10),
                "pct_52w"          : (c0 - l52_0) / (h52_0 - l52_0 + 1e-10),
                "dist_sma200"      : (c0 - sma200_0) / (sma200_0 + 1e-10),
                "fi_positive"      : 1.0 if fi_0 > 0 else 0.0,
                "stop_dist_pct"    : (c0 - round(c0 - ATR_MULT * atr_0, 2)) / (c0 + 1e-10),
            },
        }
    except Exception as e:
        log.error(f"Signal error {sym}: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY REGIME
# ─────────────────────────────────────────────────────────────────────────────
def nifty_regime() -> tuple[bool, float, float]:
    """
    Returns (is_bullish, nifty_close, sma_value).
    Uses NIFTY_SMA_PERIOD from config (default 200).
    Set NIFTY_REGIME_FILTER=False to bypass entirely.
    """
    try:
        nf = yf.download("^NSEI", period="2y", auto_adjust=True, progress=False)
        if isinstance(nf.columns, pd.MultiIndex):
            nf.columns = nf.columns.get_level_values(0)
        nf = nf.dropna(subset=["Close"])
        nf["SMA"] = nf["Close"].rolling(NIFTY_SMA_PERIOD).mean()
        c = float(nf["Close"].iloc[-1])
        s = float(nf["SMA"].dropna().iloc[-1])
        return c > s, c, s
    except Exception as e:
        log.warning(f"Nifty check failed: {e}")
        return True, 0.0, 0.0

# ─────────────────────────────────────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────────────────────────────────────
def calc_qty(capital: float, price: float, atr_val: float) -> int:
    risk_rs = capital * RISK_PCT
    rps     = ATR_MULT * atr_val
    if rps <= 0 or price <= 0:
        return 0
    ideal   = math.floor(risk_rs / rps)
    cap_max = math.floor((capital * 0.20) / price)  # max 20% per stock
    return max(min(ideal, cap_max), 0)

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTE SELL (live mode — thread safe)
# ─────────────────────────────────────────────────────────────────────────────
def execute_sell(sym: str, reason: str, ltp: float):
    with positions_lock:
        if sym not in live_positions:
            return
        p = dict(live_positions[sym])

    token   = p.get("token","")
    qty     = p["qty"]
    buy_px  = p["buy_price"]
    pnl_pct = round((ltp - buy_px) / buy_px * 100, 2)
    pnl_rs  = round((ltp - buy_px) * qty, 0)
    result  = "PROFIT" if pnl_rs >= 0 else "LOSS"

    log.info(f"SELL {sym}: {reason} ltp={ltp:.2f} pnl={pnl_pct:+.1f}%")

    oid = place_order(sym, token, qty, "SELL")
    if oid:
        filled = wait_fill(oid, sym)
        tg(
            f"SELL <b>{sym}</b>\n"
            f"Reason: {reason}\n"
            f"Price: Rs{ltp:.2f}  Qty: {qty}\n"
            f"PnL: Rs{pnl_rs:+.0f} ({pnl_pct:+.1f}%) — {result}\n"
            f"Order: {'CONFIRMED' if filled else 'UNCONFIRMED — check manually!'}",
            urgent=(reason == "STOP_LOSS")
        )
        with positions_lock:
            live_positions.pop(sym, None)
        sold_today.add(sym)
        save_positions()
    else:
        tg(
            f"SELL FAILED: <b>{sym}</b>\n"
            f"Reason: {reason} | LTP: Rs{ltp:.2f}\n"
            f"MANUAL ACTION REQUIRED NOW",
            urgent=True
        )

# ─────────────────────────────────────────────────────────────────────────────
# TRAILING STOP UPDATE (live mode)
# ─────────────────────────────────────────────────────────────────────────────
def update_trailing_stops():
    with positions_lock:
        syms = list(live_positions.keys())
    for sym in syms:
        with positions_lock:
            if sym not in live_positions:
                continue
            p = dict(live_positions[sym])
        ltp = get_ltp(sym, p.get("token",""))
        if ltp is None:
            continue
        with positions_lock:
            if sym not in live_positions:
                continue
            live_positions[sym]["peak"] = max(live_positions[sym]["peak"], ltp)
            peak = live_positions[sym]["peak"]
        try:
            df = yf.download(f"{sym}.NS", period="3mo",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            live_atr = float(_atr(df["High"], df["Low"], df["Close"], 14).iloc[-1])
        except Exception:
            live_atr = abs(ltp - p["stop_loss"]) / ATR_MULT
        new_sl = round(peak - ATR_MULT * live_atr, 2)
        with positions_lock:
            if sym in live_positions and new_sl > live_positions[sym]["stop_loss"]:
                old = live_positions[sym]["stop_loss"]
                live_positions[sym]["stop_loss"] = new_sl
                log.info(f"{sym}: Trail SL {old:.2f} -> {new_sl:.2f}")
    save_positions()

# ─────────────────────────────────────────────────────────────────────────────
# CONTINUOUS SL MONITOR THREAD (live mode only)
# ─────────────────────────────────────────────────────────────────────────────
def sl_monitor_loop():
    log.info("SL monitor thread started — checking every 30s.")
    last_trail = time.time()
    while True:
        now = datetime.now().time()
        if now >= MARKET_CLOSE:
            log.info("SL monitor: market closed, stopping.")
            break
        if now < MARKET_OPEN:
            time.sleep(10)
            continue
        with positions_lock:
            syms = list(live_positions.keys())
        for sym in syms:
            with positions_lock:
                if sym not in live_positions:
                    continue
                p = dict(live_positions[sym])
            ltp = get_ltp(sym, p.get("token",""))
            if ltp is None:
                log.warning(f"SL monitor: no LTP for {sym}")
                continue
            if ltp <= p["stop_loss"]:
                log.info(f"STOP LOSS HIT: {sym} LTP={ltp:.2f} SL={p['stop_loss']:.2f}")
                threading.Thread(
                    target=execute_sell,
                    args=(sym, "STOP_LOSS", ltp),
                    daemon=True
                ).start()
        if time.time() - last_trail >= TRAIL_INTERVAL:
            threading.Thread(target=update_trailing_stops, daemon=True).start()
            last_trail = time.time()
        time.sleep(SL_CHECK_INTERVAL)
    log.info("SL monitor exited.")

# ─────────────────────────────────────────────────────────────────────────────
# CORE ENGINE — used by both paper and live modes
# Manages existing positions + scans all stocks + builds full report
# ─────────────────────────────────────────────────────────────────────────────
def run_engine(token_map: dict, capital: float, bull: bool,
               nifty_close: float, nifty_sma: float) -> str:
    """
    Full portfolio manager + market scan.
    Returns the complete Telegram/console report string.
    Updates live_positions in place.
    """
    mode_tag = "LIVE" if LIVE_MODE else "PAPER"
    report = (
        f"{'LIVE' if LIVE_MODE else 'PAPER'} Algo Report\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    )

    # ── Nifty regime ─────────────────────────────────────────────────────────
    # ── Nifty regime display + NIFTY_REGIME_FILTER toggle ───────────────────────
    if not NIFTY_REGIME_FILTER:
        bull = True   # bypass: ignore regime, scan all stocks anyway
        report += (f"Market: {'BULLISH' if nifty_close > nifty_sma else 'BEARISH'} "
                   f"(Nifty {nifty_close:.0f} vs SMA{NIFTY_SMA_PERIOD} {nifty_sma:.0f})\n"
                   f"REGIME FILTER OFF — scanning all stocks regardless\n\n")
    elif bull:
        report += (f"Market: BULLISH "
                   f"(Nifty {nifty_close:.0f} > SMA{NIFTY_SMA_PERIOD} {nifty_sma:.0f})\n\n")
    else:
        report += (f"Market: BEARISH "
                   f"(Nifty {nifty_close:.0f} < SMA{NIFTY_SMA_PERIOD} {nifty_sma:.0f})\n"
                   f"NEW ENTRIES BLOCKED — set NIFTY_REGIME_FILTER=False to override\n\n")

    # ── Section 1: Manage existing positions ─────────────────────────────────
    report += "PORTFOLIO MANAGER:\n"
    with positions_lock:
        syms_held = list(live_positions.keys())

    if not syms_held:
        report += "No open positions to manage.\n\n"
    else:
        to_sell = []
        for sym in syms_held:
            with positions_lock:
                if sym not in live_positions:
                    continue
                p = dict(live_positions[sym])

            # Get price — use live LTP if token available, else yfinance
            ltp = None
            tok = p.get("token","")
            if tok and LIVE_MODE:
                ltp = get_ltp(sym, tok)

            if ltp is None:
                try:
                    df_m = yf.download(f"{sym}.NS", period="5d",
                                       auto_adjust=True, progress=False)
                    if isinstance(df_m.columns, pd.MultiIndex):
                        df_m.columns = df_m.columns.get_level_values(0)
                    ltp = float(df_m["Close"].dropna().iloc[-1])
                    live_atr = float(_atr(df_m["High"], df_m["Low"],
                                          df_m["Close"], 14).dropna().iloc[-1])
                except Exception:
                    report += f"  {sym}: price unavailable — holding.\n"
                    continue
            else:
                try:
                    df_m = yf.download(f"{sym}.NS", period="1mo",
                                       auto_adjust=True, progress=False)
                    if isinstance(df_m.columns, pd.MultiIndex):
                        df_m.columns = df_m.columns.get_level_values(0)
                    live_atr = float(_atr(df_m["High"], df_m["Low"],
                                          df_m["Close"], 14).dropna().iloc[-1])
                except Exception:
                    live_atr = abs(ltp - p["stop_loss"]) / ATR_MULT

            sl      = p["stop_loss"]
            buy_px  = p["buy_price"]
            qty     = p["qty"]
            pnl_pct = round((ltp - buy_px) / buy_px * 100, 2)

            if ltp <= sl:
                pnl_rs = round((ltp - buy_px) * qty, 0)
                result = "PROFIT" if pnl_rs >= 0 else "LOSS"
                report += (f"  SELL {sym}: Stop Loss Hit\n"
                           f"  Sold at: Rs{ltp:.2f} | PnL: Rs{pnl_rs:+.0f} ({result})\n")
                to_sell.append((sym, ltp))
            else:
                new_sl = round(ltp - live_atr * ATR_MULT, 2)
                if new_sl > sl:
                    with positions_lock:
                        if sym in live_positions:
                            live_positions[sym]["stop_loss"] = new_sl
                    report += (f"  {sym}: Holding Rs{ltp:.2f} ({pnl_pct:+.1f}%) "
                               f"| SL raised to Rs{new_sl:.2f}\n")
                else:
                    report += (f"  {sym}: Holding Rs{ltp:.2f} ({pnl_pct:+.1f}%) "
                               f"| SL Rs{sl:.2f}\n")

        # Process sells
        for sym, ltp in to_sell:
            with positions_lock:
                if sym not in live_positions:
                    continue
                p = dict(live_positions[sym])
            tok = p.get("token","")
            qty = p["qty"]
            oid = place_order(sym, tok, qty, "SELL")
            if oid:
                wait_fill(oid, sym)
            with positions_lock:
                live_positions.pop(sym, None)
            sold_today.add(sym)

        save_positions()
        report += "\n"

    # ── Load ML signal classifier ────────────────────────────────────────────
    ML_MODEL      = None
    ML_FEATURES   = None
    ML_ACTIVE     = False
    ML_FILTER     = 0.40   # reject if prob < this (statistically validated)
    # Confidence sizing tiers (validated by 18% WR gap, NOT by fine-grained prob)
    # SAFE: only two tiers — accept/reject. No tiered sizing (not enough data above 0.45)
    try:
        import joblib
        if os.path.exists("signal_classifier.pkl"):
            saved       = joblib.load("signal_classifier.pkl")
            ML_MODEL    = saved["model"]
            ML_FEATURES = saved["features"]
            ML_ACTIVE   = True
            log.info(f"ML classifier loaded (AUC={saved.get('auc',0):.4f})")
        else:
            log.warning("signal_classifier.pkl not found — running without ML filter")
    except Exception as e:
        log.warning(f"ML load failed: {e} — running without ML filter")

    # Nifty features needed for ML scoring
    try:
        nifty_df_ml  = yf.download("^NSEI", period="3mo", auto_adjust=True, progress=False)
        if isinstance(nifty_df_ml.columns, pd.MultiIndex):
            nifty_df_ml.columns = nifty_df_ml.columns.get_level_values(0)
        nifty_sma200_ml = float(nifty_df_ml["Close"].rolling(200).mean().iloc[-1])
        nifty_now_ml    = float(nifty_df_ml["Close"].iloc[-1])
        nifty_ret5_ml   = float(nifty_df_ml["Close"].pct_change(5).iloc[-1])
        nifty_str_ml    = (nifty_now_ml - nifty_sma200_ml) / (nifty_sma200_ml + 1e-10)
    except Exception:
        nifty_sma200_ml = nifty_sma; nifty_now_ml = nifty_close
        nifty_ret5_ml   = 0.0;       nifty_str_ml  = 0.0

    def get_ml_prob(sym: str, feats: dict) -> float:
        """Score a signal. Returns prob 0-1. -1 = ML bypassed for this stock."""
        if not ML_ACTIVE:
            return -1.0
        # Bypass for stocks with <5 historical signals (model not calibrated)
        if sym in ML_BYPASS_STOCKS:
            log.info(f"  ML bypass for {sym} (sparse history) — auto-accept")
            return 1.0
        try:
            row = {
                "pullback_depth"  : feats.get("pullback_depth", 50),
                "dist_ema50"      : feats.get("dist_ema50", 0),
                "dist_ema20"      : feats.get("dist_ema20", 0),
                "rsi14"           : feats.get("rsi14", 50),
                "atr_ratio"       : feats.get("atr_ratio", 1),
                "atr_pct"         : feats.get("atr_pct", 0.02),
                "vol_surge"       : feats.get("vol_surge", 1),
                "pct_52w"         : feats.get("pct_52w", 0.5),
                "dist_sma200"     : feats.get("dist_sma200", 0),
                "nifty_strength"  : nifty_str_ml,
                "nifty_ret5"      : nifty_ret5_ml,
                "days_since_signal": 60,   # conservative default
                "fi_positive"     : feats.get("fi_positive", 0),
                "stop_dist_pct"   : feats.get("stop_dist_pct", 0.05),
            }
            X = np.array([[row[f] for f in ML_FEATURES]])
            prob = float(ML_MODEL.predict_proba(X)[0, 1])
            return prob
        except Exception as e:
            log.warning(f"ML score failed for {sym}: {e}")
            return -1.0

    # ── Section 2: Scan all stocks for new signals ────────────────────────────
    report += "NEW ALERTS:\n"
    if ML_ACTIVE:
        report += f"  ML filter active (threshold: {ML_FILTER:.2f})\n"
    new_found = 0

    with positions_lock:
        currently_owned = set(live_positions.keys())

    active_universe = get_active_universe()
    for sym in active_universe:
        if new_found >= MAX_NEW_PER_RUN:
            break
        if sym in currently_owned or sym in sold_today:
            continue

        try:
            df = yf.download(f"{sym}.NS", period="6mo",
                             auto_adjust=True, progress=False)
            if df is None or df.empty or len(df) < 60:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])

            sig = check_signals(df, token_map, sym, nifty_bull=bull)
            if sig is None or not sig["signal"]:
                if VERBOSE_SCAN:
                    # Show exactly which screen failed for each stock
                    if sig:
                        s1 = "Y" if sig["s1"] else "N"
                        s2 = "Y" if sig["s2"] else "N"
                        s3 = "Y" if sig["s3"] else "N"
                        trig = sig["trigger"]
                        log.info(f"  {sym:<14} S1={s1} S2={s2} S3={s3} "
                                 f"trigger={trig} → no signal")
                continue

            price   = sig["price"]
            atr_val = sig["atr"]
            sl      = sig["stop_loss"]
            trigger = sig["trigger"]

            if price < MIN_PRICE:
                continue

            # ── ML FILTER + CONFIDENCE SIZING ────────────────────────────────
            ml_prob   = get_ml_prob(sym, sig.get("ml_feats", {}))
            ml_tag    = ""
            size_mult = 1.0

            if ml_prob >= 0 and ML_FILTER_ENABLED:
                if ml_prob < ML_FILTER_THRESHOLD:
                    log.info(f"  {sym}: ML REJECTED (prob={ml_prob:.3f} < {ML_FILTER_THRESHOLD})")
                    report += (f"  FILTERED {sym}: ML prob={ml_prob:.2f} "
                               f"< {ML_FILTER_THRESHOLD} — skipped\n")
                    continue
            elif not ML_FILTER_ENABLED:
                log.debug(f"  {sym}: ML filter OFF — signal accepted without scoring")
                # Two-tier sizing: statistically validated
                if ml_prob >= 0.45:
                    size_mult = 1.30
                    ml_tag = f" | ML={ml_prob:.2f} (+30% size)"
                else:
                    size_mult = 1.00
                    ml_tag = f" | ML={ml_prob:.2f}"
            # ─────────────────────────────────────────────────────────────────

            # Get token and live price
            tok = token_map.get(sym, "")
            if LIVE_MODE and tok:
                live_price = get_ltp(sym, tok)
                if live_price:
                    price = live_price
                    sl    = round(price - ATR_MULT * atr_val, 2)

            qty     = calc_qty(capital, price, atr_val)
            qty_ml  = max(1, round(qty * size_mult))
            cost    = qty_ml * price
            if cost > capital * 0.20:   # never more than 20% in one position
                qty_ml = max(1, int(capital * 0.20 / price))
                cost   = qty_ml * price
            risk_rs = qty_ml * (price - sl)

            if qty_ml < 1:
                continue

            mode_label = "LIVE BUY" if LIVE_MODE else "PAPER BUY"
            report += (f"  {mode_label} {sym}{ml_tag}\n"
                       f"  Trigger: {trigger} | Price: Rs{price:.2f} | Qty: {qty_ml}\n"
                       f"  SL: Rs{sl:.2f} | Risk: Rs{risk_rs:.0f} | Cost: Rs{cost:,.0f}\n\n")
            new_found += 1

            # Place order (real in live mode, simulated in paper mode)
            oid = place_order(sym, tok, qty_ml, "BUY")
            if oid and wait_fill(oid, sym):
                with positions_lock:
                    live_positions[sym] = {
                        "token"      : tok,
                        "buy_price"  : price,
                        "qty"        : qty_ml,
                        "stop_loss"  : sl,
                        "entry_date" : datetime.now().strftime("%Y-%m-%d"),
                        "order_id"   : oid,
                        "peak"       : price,
                        "ml_prob"    : round(ml_prob, 3),
                        "size_mult"  : size_mult,
                    }
                capital -= cost
                save_positions()

        except Exception as e:
            log.error(f"{sym}: scan error — {e}")
            continue

    if new_found == 0:
        report += "  No valid setups found today.\n"

    return report

# ─────────────────────────────────────────────────────────────────────────────
# EOD SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
def eod_summary():
    lines = [f"EOD Summary — {datetime.now().strftime('%Y-%m-%d')}",
             f"Open positions: {len(live_positions)}"]
    with positions_lock:
        for sym, p in live_positions.items():
            tok = p.get("token","")
            ltp = get_ltp(sym, tok) if tok else None
            if ltp:
                pnl = round((ltp - p["buy_price"]) / p["buy_price"] * 100, 2)
                lines.append(f"  {sym}: Rs{ltp:.2f} | SL Rs{p['stop_loss']:.2f} | {pnl:+.1f}%")
            else:
                lines.append(f"  {sym}: LTP unavailable")
    if sold_today:
        lines.append(f"Sold today: {', '.join(sold_today)}")
    tg("\n".join(lines))

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global live_positions

    print("=" * 80)
    print(f"  TRIPLE SCREEN DEFENSE BOT  |  {'LIVE MODE' if LIVE_MODE else 'PAPER MODE'}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # ── Login ─────────────────────────────────────────────────────────────────
    api = login()
    if not api:
        return

    # ── Token map (optional in paper mode) ──────────────────────────────────
    token_map = load_token_map()
    if not token_map:
        if LIVE_MODE:
            tg("CRITICAL: Token map empty — live orders need tokens. Aborting.", urgent=True)
            return
        else:
            log.warning("Token map unavailable — paper mode continues with yfinance prices.")
            print("  Token map unavailable — paper mode works fine without it.\n")

    # ── Load saved positions ──────────────────────────────────────────────────
    live_positions = load_positions()

    # ── Get margin ────────────────────────────────────────────────────────────
    capital = get_free_margin()
    print(f"  Capital available: Rs{capital:,.0f}")

    # ── Nifty regime ──────────────────────────────────────────────────────────
    bull, nifty_close, nifty_sma = nifty_regime()

    # ─────────────────────────────────────────────────────────────────────────
    # PAPER MODE: run once, print full report, exit
    # Same behavior as your old bot — works any time of day
    # ─────────────────────────────────────────────────────────────────────────
    if not LIVE_MODE:
        report = run_engine(token_map, capital, bull, nifty_close, nifty_sma)
        tg(report)
        return

    # ─────────────────────────────────────────────────────────────────────────
    # LIVE MODE: continuous all-day operation
    # ─────────────────────────────────────────────────────────────────────────
    now = datetime.now().time()

    # If before market open, wait
    if now < MARKET_OPEN:
        wait_sec = ((MARKET_OPEN.hour - now.hour) * 3600 +
                    (MARKET_OPEN.minute - now.minute) * 60 - now.second)
        log.info(f"Market opens in {max(wait_sec,0)//60}m — waiting...")
        time.sleep(max(wait_sec - 30, 0))

    if datetime.now().time() > MARKET_CLOSE:
        tg("Market already closed. Run without --live for a paper report.")
        return

    tg(
        f"<b>Live Bot Active</b> — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Positions loaded: {len(live_positions)}\n"
        f"Capital: Rs{capital:,.0f}\n"
        f"SL monitor: every {SL_CHECK_INTERVAL}s"
    )

    # Start SL monitor thread
    monitor = threading.Thread(target=sl_monitor_loop, daemon=True)
    monitor.start()

    # Wait for 9:20 AM scan
    now = datetime.now().time()
    if now < SCAN_TIME:
        wait_sec = ((SCAN_TIME.hour - now.hour) * 3600 +
                    (SCAN_TIME.minute - now.minute) * 60)
        log.info(f"Waiting {wait_sec}s for morning scan...")
        time.sleep(max(wait_sec, 0))

    # Morning scan — full engine run
    report = run_engine(token_map, capital, bull, nifty_close, nifty_sma)
    tg(report)

    # Keep alive until EOD
    eod_sent = False
    hb = 0
    while True:
        now = datetime.now().time()
        if now >= MARKET_CLOSE and not eod_sent:
            eod_summary()
            eod_sent = True
            log.info("EOD done. Shutting down in 5 min.")
            time.sleep(300)
            break
        hb += 1
        if hb % 5 == 0:
            with positions_lock:
                n = len(live_positions)
            log.info(f"Heartbeat: {n} positions open.")
        time.sleep(60)

    monitor.join(timeout=15)
    log.info("Bot shut down cleanly.")

if __name__ == "__main__":
    main()
