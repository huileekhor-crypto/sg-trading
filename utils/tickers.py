"""
Scan universe: SPY + QQQ holdings from UW ETF endpoint (primary),
sector-organised fallback list if UW is unavailable.
Cached in-process for 24 h so the scan job never hits the endpoint twice.
"""

import os
import time

# ─── Live fetch from UW ───────────────────────────────────────────────────────

_universe_cache = {"tickers": None, "ts": 0.0}
_UNIVERSE_TTL = 86400  # 24 h


def _fetch_etf_holdings(etf, limit=600):
    """Return stock tickers for an ETF from UW /api/etfs/{etf}/holdings."""
    uw_key = os.environ.get("UW_API_KEY", "")
    if not uw_key:
        return []
    try:
        import requests
        r = requests.get(
            f"https://api.unusualwhales.com/api/etfs/{etf}/holdings",
            params={"limit": limit},
            headers={"Authorization": f"Bearer {uw_key}", "UW-CLIENT-API-ID": "100001"},
            timeout=15,
        )
        if not r.ok:
            return []
        tickers = []
        for row in r.json().get("data", []):
            if row.get("type") != "stock":
                continue
            t = str(row.get("ticker", "")).upper().strip()
            if not t:
                continue
            t = t.replace(".", "-")   # BRK.B / BF.B → BRK-B / BF-B (Yahoo Finance format)
            tickers.append(t)
        return tickers
    except Exception:
        return []


def _get_live_universe():
    """
    Fetch SPY (503 stocks) + QQQ (101 stocks) holdings from UW.
    Result is cached for 24 h. Returns [] on any failure so callers
    can fall through to the static fallback.
    """
    now = time.time()
    if _universe_cache["tickers"] is not None and now - _universe_cache["ts"] < _UNIVERSE_TTL:
        return _universe_cache["tickers"]

    spy = _fetch_etf_holdings("SPY", limit=600)
    qqq = _fetch_etf_holdings("QQQ", limit=150)

    if not spy and not qqq:
        print("[TICKERS] WARNING: UW ETF holdings fetch failed for both SPY and QQQ — falling back to static list")
        return []

    qqq_new = len([t for t in qqq if t not in set(spy)])
    seen = set()
    combined = []
    for t in spy + qqq:
        if t not in seen:
            seen.add(t)
            combined.append(t)

    print(f"[TICKERS] Live universe loaded from UW: {len(spy)} SPY + {qqq_new} QQQ-only = {len(combined)} unique tickers")
    _universe_cache["tickers"] = combined
    _universe_cache["ts"] = now
    return combined


# ─── Static fallback (used only when UW ETF endpoint is unavailable) ─────────

_IT = [
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "ADBE", "CRM", "CSCO", "ACN", "NOW",
    "IBM", "INTU", "TXN", "QCOM", "AMD", "INTC", "AMAT", "LRCX", "KLAC", "MU",
    "ADI", "MRVL", "CDNS", "SNPS", "MCHP", "NXPI", "ON", "MPWR", "SWKS", "QRVO",
    "ARM", "TSM", "ASML", "ANET", "MSI", "GLW", "TEL", "JNPR", "HPQ", "HPE",
    "STX", "NTAP", "CTSH", "IT", "EPAM", "CDW", "DXC", "LDOS", "KEYS", "ANSS",
    "ZBRA", "PTC", "TRMB", "AKAM", "DDOG", "ZS", "CRWD", "PANW", "FTNT", "OKTA",
    "NET", "S", "GTLB", "MDB", "SNOW", "PLTR", "PATH", "AI", "CFLT", "HUBS",
    "TEAM", "WDAY", "ADSK", "ZM", "DOCU", "TWLO", "BOX", "MNDY",
    "FIS", "FISV", "GPN", "PAYC", "ADP", "PAYX", "FSLR", "ENPH",
    "SMCI", "NBIS", "IONQ", "RGTI", "QBTS", "CAMT", "LSCC", "ARRY", "GEN", "GDDY",
]
_COMM = [
    "META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    "CHTR", "WBD", "PARA", "FOXA", "FOX", "SNAP", "MTCH", "IAC", "PINS", "TTWO", "EA",
]
_CD = [
    "AMZN", "TSLA", "BKNG", "SHOP", "MELI", "SE", "BABA", "JD", "PDD",
    "EBAY", "ETSY", "W", "DASH", "ABNB", "LYFT", "UBER", "RBLX",
    "HD", "LOW", "TGT", "TJX", "ROST", "BURL", "FIVE", "DG", "DLTR", "BBY",
    "M", "JWN", "KSS", "GPS", "MCD", "SBUX", "CMG", "YUM", "DPZ", "DRI", "QSR",
    "MAR", "HLT", "RCL", "CCL", "NCLH", "LVS", "WYNN", "MGM", "CZR",
    "NKE", "LULU", "VFC", "PVH", "RL", "TPR", "HBI",
    "F", "GM", "APTV", "LEA", "BWA", "ORLY", "AZO", "GPC", "LKQ",
    "PHM", "LEN", "DHI", "TOL", "NVR",
]
_CS = [
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "MDLZ", "KHC", "GIS",
    "K", "CPB", "MKC", "CAG", "HRL", "TSN", "ADM", "BG",
    "CL", "CHD", "EL", "KMB", "CLX", "STZ", "TAP", "MNST", "SYY", "USFD",
]
_EN = [
    "XOM", "CVX", "COP", "EOG", "PXD", "DVN", "FANG", "MRO", "APA", "HES", "OXY",
    "HAL", "SLB", "BKR", "VLO", "PSX", "MPC", "KMI", "WMB", "OKE", "ET", "TRGP",
]
_FIN = [
    "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "USB", "TFC", "PNC",
    "RF", "FITB", "HBAN", "MTB", "CFG", "KEY", "SCHW", "BLK", "NDAQ", "CBOE",
    "CME", "ICE", "SPGI", "MCO", "MSCI", "CB", "PGR", "ALL", "TRV", "HIG",
    "AIG", "PRU", "MET", "AFL", "MMC", "AON", "WTW", "BRO", "AJG",
    "V", "MA", "AXP", "COF", "DFS", "SYF", "ALLY", "COIN", "HOOD", "SQ", "PYPL",
]
_HC = [
    "LLY", "JNJ", "ABBV", "MRK", "PFE", "BMY", "AMGN", "GILD", "BIIB",
    "VRTX", "REGN", "MRNA", "BNTX", "ALNY", "INCY", "NVO", "AZN",
    "UNH", "CI", "CVS", "HCA", "MCK", "CAH", "MOH", "HUM", "CNC", "ABC",
    "TMO", "DHR", "ABT", "ISRG", "SYK", "EW", "MDT", "BSX", "GEHC",
    "IDXX", "DXCM", "ILMN", "RMD", "PODD", "HOLX", "BAX", "BDX", "ZBH",
    "ALGN", "COO", "WST", "IQV", "VEEV", "MTD", "A", "WAT", "RVTY",
    "DGX", "LH", "VTRS", "HSIC",
]
_IND = [
    "BA", "LMT", "RTX", "NOC", "GD", "TDG", "HEI", "TXT", "LHX", "HII",
    "GE", "HON", "ETN", "EMR", "ITW", "PH", "DOV", "ROK", "AME", "XYL",
    "IEX", "IR", "GNRC", "ROP", "FTV", "CARR", "OTIS", "JCI", "SWK",
    "TT", "ALLE", "HUBB", "NDSN", "AOS", "CAT", "DE", "CTAS", "VRSK",
    "RSG", "WM", "FAST", "GWW", "PCAR", "ODFL", "SAIA", "JBHT", "KNX",
    "XPO", "CHRW", "EXPD", "FDX", "UPS", "LUV", "DAL", "UAL", "AAL", "ALK",
    "NSC", "CSX", "UNP", "CP", "CNI", "MMM",
]
_MAT = [
    "LIN", "APD", "SHW", "ECL", "PPG", "IFF", "EMN", "FMC", "CE", "HUN",
    "ALB", "CF", "MOS", "NEM", "FCX", "AA", "NUE", "STLD", "RS",
    "SEE", "BALL", "PKG", "IP", "WRK", "CCK", "AVY",
]
_UT = [
    "NEE", "SO", "DUK", "D", "AEP", "EXC", "SRE", "PCG", "ED", "XEL",
    "WEC", "DTE", "ES", "ETR", "FE", "NI", "CNP", "AES", "EIX", "CMS",
    "PPL", "LNT", "EVRG", "ATO", "AWK", "CEG", "VST",
]
_RE = [
    "AMT", "CCI", "EQIX", "SBAC", "IRM", "PLD", "PSA", "EXR", "CUBE",
    "EQR", "AVB", "ESS", "MAA", "UDR", "CPT", "INVH",
    "SPG", "KIM", "REG", "FRT", "O", "NNN", "ADC", "BXP", "VNO",
    "WELL", "VTR", "VICI", "GLPI",
]

_FALLBACK = list(dict.fromkeys(
    _IT + _COMM + _CD + _CS + _EN + _FIN + _HC + _IND + _MAT + _UT + _RE
))


# ─── Public API ───────────────────────────────────────────────────────────────

WATCHLIST_DEFAULT = [
    "NBIS", "MU", "NVDA", "AMD", "MSFT", "AAPL", "TSLA", "META", "GOOGL", "AMZN",
    "SMCI", "PLTR", "AI", "CRWD", "DDOG", "SNOW", "COIN", "SHOP", "MELI", "SE",
    "IONQ", "RGTI", "QBTS", "ARRY", "GTLS", "AEHR", "CAMT", "LSCC",
]


def get_scan_universe(extra_watchlist=None):
    """
    Primary: SPY + QQQ live holdings from UW (503 + 101 stocks, deduplicated).
    Fallback: static sector list (~480 tickers) if UW is unavailable.
    extra_watchlist tickers (e.g. from UW screener) are appended and deduplicated.
    """
    base = _get_live_universe() or _FALLBACK

    seen = set()
    universe = []
    for t in base + (extra_watchlist or []):
        if t and t not in seen:
            seen.add(t)
            universe.append(t)
    return universe
