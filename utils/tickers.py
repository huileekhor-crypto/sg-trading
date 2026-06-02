# Full S&P 500 + NASDAQ 100 universe (~480 unique tickers after dedup)
# Organized by GICS sector for maintainability

# ─── Information Technology ───────────────────────────────────────────────
_IT = [
    # Mega-cap platform
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "ADBE", "CRM", "CSCO", "ACN", "NOW",
    "IBM", "INTU",
    # Semiconductors
    "TXN", "QCOM", "AMD", "INTC", "AMAT", "LRCX", "KLAC", "MU", "ADI", "MRVL",
    "CDNS", "SNPS", "MCHP", "NXPI", "ON", "MPWR", "SWKS", "QRVO", "ARM", "TSM",
    "ASML",
    # Networking / hardware
    "ANET", "MSI", "GLW", "TEL", "JNPR", "HPQ", "HPE", "STX", "NTAP",
    # IT services
    "CTSH", "IT", "EPAM", "CDW", "DXC", "LDOS",
    # Test, measurement, EDA
    "KEYS", "ANSS", "ZBRA", "PTC", "TRMB", "AKAM",
    # Cloud / SaaS / cybersecurity
    "DDOG", "ZS", "CRWD", "PANW", "FTNT", "OKTA", "NET", "S", "GTLB",
    "MDB", "SNOW", "PLTR", "PATH", "AI", "CFLT", "HUBS", "TEAM", "WDAY",
    "ADSK", "ZM", "DOCU", "TWLO", "BOX", "MNDY",
    # Payments processing infrastructure
    "FIS", "FISV", "GPN", "PAYC", "ADP", "PAYX",
    # Clean energy / solar
    "FSLR", "ENPH",
    # AI / quantum / edge
    "SMCI", "NBIS", "IONQ", "RGTI", "QBTS", "CAMT", "LSCC", "ARRY",
    # Consumer tech
    "GEN", "GDDY",
]

# ─── Communication Services ───────────────────────────────────────────────
_COMM = [
    "META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    "CHTR", "WBD", "PARA", "FOXA", "FOX", "SNAP", "MTCH", "IAC",
    "PINS", "TTWO", "EA",
]

# ─── Consumer Discretionary ───────────────────────────────────────────────
_CD = [
    # E-commerce / platforms
    "AMZN", "TSLA", "BKNG", "SHOP", "MELI", "SE", "BABA", "JD", "PDD",
    "EBAY", "ETSY", "W", "DASH", "ABNB", "LYFT", "UBER", "RBLX",
    # Retail — general
    "HD", "LOW", "TGT", "TJX", "ROST", "BURL", "FIVE", "DG", "DLTR", "BBY",
    "M", "JWN", "KSS", "GPS",
    # Restaurants / leisure
    "MCD", "SBUX", "CMG", "YUM", "DPZ", "DRI", "QSR",
    "MAR", "HLT", "RCL", "CCL", "NCLH", "LVS", "WYNN", "MGM", "CZR",
    # Apparel / brands
    "NKE", "LULU", "VFC", "PVH", "RL", "TPR", "HBI",
    # Autos
    "F", "GM", "APTV", "LEA", "BWA",
    # Auto parts
    "ORLY", "AZO", "GPC", "LKQ",
    # Homebuilders
    "PHM", "LEN", "DHI", "TOL", "NVR",
]

# ─── Consumer Staples ─────────────────────────────────────────────────────
_CS = [
    # Retail
    "WMT", "COST",
    # Food & beverage
    "PG", "KO", "PEP", "PM", "MO", "MDLZ", "KHC", "GIS",
    "K", "CPB", "MKC", "CAG", "HRL", "TSN", "ADM", "BG",
    # Household / personal care
    "CL", "CHD", "EL", "KMB", "CLX",
    # Alcohol / beverages
    "STZ", "TAP", "MNST",
    # Food distribution
    "SYY", "USFD",
]

# ─── Energy ───────────────────────────────────────────────────────────────
_EN = [
    # E&P
    "XOM", "CVX", "COP", "EOG", "PXD", "DVN", "FANG", "MRO", "APA", "HES", "OXY",
    # Oilfield services
    "HAL", "SLB", "BKR",
    # Refining
    "VLO", "PSX", "MPC",
    # Pipelines / midstream
    "KMI", "WMB", "OKE", "ET", "TRGP",
]

# ─── Financials ───────────────────────────────────────────────────────────
_FIN = [
    # Banks
    "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "USB", "TFC", "PNC",
    "RF", "FITB", "HBAN", "MTB", "CFG", "KEY",
    # Capital markets / exchanges
    "SCHW", "BLK", "NDAQ", "CBOE", "CME", "ICE", "SPGI", "MCO", "MSCI",
    # Insurance
    "CB", "PGR", "ALL", "TRV", "HIG", "AIG", "PRU", "MET", "AFL",
    # Insurance brokers
    "MMC", "AON", "WTW", "BRO", "AJG",
    # Payments / credit
    "V", "MA", "AXP", "COF", "DFS", "SYF", "ALLY",
    # Fintech
    "COIN", "HOOD", "SQ", "PYPL",
]

# ─── Health Care ──────────────────────────────────────────────────────────
_HC = [
    # Large pharma / biotech
    "LLY", "JNJ", "ABBV", "MRK", "PFE", "BMY", "AMGN", "GILD", "BIIB",
    "VRTX", "REGN", "MRNA", "BNTX", "ALNY", "INCY", "NVO", "AZN",
    # Managed care / distribution
    "UNH", "CI", "CVS", "HCA", "MCK", "CAH", "MOH", "HUM", "CNC", "ABC",
    # Medical devices
    "TMO", "DHR", "ABT", "ISRG", "SYK", "EW", "MDT", "BSX", "GEHC",
    "IDXX", "DXCM", "ILMN", "RMD", "PODD", "HOLX", "BAX", "BDX", "ZBH",
    "ALGN", "COO", "WST",
    # Life science tools / diagnostics
    "IQV", "VEEV", "MTD", "A", "WAT", "RVTY", "DGX", "LH",
    # Other
    "VTRS", "HSIC",
]

# ─── Industrials ──────────────────────────────────────────────────────────
_IND = [
    # Aerospace & defense
    "BA", "LMT", "RTX", "NOC", "GD", "TDG", "HEI", "TXT", "LHX", "HII",
    # Diversified industrials / machinery
    "GE", "HON", "ETN", "EMR", "ITW", "PH", "DOV", "ROK", "AME", "XYL",
    "IEX", "IR", "GNRC", "ROP", "FTV", "CARR", "OTIS", "JCI", "SWK",
    "TT", "ALLE", "HUBB", "NDSN", "AOS",
    # Heavy equipment
    "CAT", "DE",
    # Commercial services / staffing
    "CTAS", "VRSK", "LDOS",
    # Waste management
    "RSG", "WM",
    # Distribution
    "FAST", "GWW",
    # Trucking / freight
    "PCAR", "ODFL", "SAIA", "JBHT", "KNX", "XPO", "CHRW", "EXPD",
    # Parcel
    "FDX", "UPS",
    # Airlines
    "LUV", "DAL", "UAL", "AAL", "ALK",
    # Rails
    "NSC", "CSX", "UNP", "CP", "CNI",
    # Other
    "MMM",
]

# ─── Materials ────────────────────────────────────────────────────────────
_MAT = [
    # Industrial gases / chemicals
    "LIN", "APD", "SHW", "ECL", "PPG", "IFF", "EMN", "FMC", "CE", "HUN",
    # Specialty
    "ALB", "CF", "MOS",
    # Metals & mining
    "NEM", "FCX", "AA", "NUE", "STLD", "RS",
    # Packaging
    "SEE", "BALL", "PKG", "IP", "WRK", "CCK", "AVY",
]

# ─── Utilities ────────────────────────────────────────────────────────────
_UT = [
    "NEE", "SO", "DUK", "D", "AEP", "EXC", "SRE", "PCG", "ED", "XEL",
    "WEC", "DTE", "ES", "ETR", "FE", "NI", "CNP", "AES", "EIX", "CMS",
    "PPL", "LNT", "EVRG", "ATO", "AWK", "CEG", "VST",
]

# ─── Real Estate ──────────────────────────────────────────────────────────
_RE = [
    # Tower / data
    "AMT", "CCI", "EQIX", "SBAC", "IRM",
    # Industrial / logistics
    "PLD",
    # Self-storage
    "PSA", "EXR", "CUBE",
    # Residential
    "EQR", "AVB", "ESS", "MAA", "UDR", "CPT", "INVH",
    # Retail
    "SPG", "KIM", "REG", "FRT", "O", "NNN", "ADC",
    # Office
    "BXP", "VNO",
    # Healthcare REIT
    "WELL", "VTR",
    # Gaming REIT
    "VICI", "GLPI",
]

# ─── High-conviction watchlist (core edge setups) ─────────────────────────
WATCHLIST_DEFAULT = [
    "NBIS", "MU", "NVDA", "AMD", "MSFT", "AAPL", "TSLA", "META", "GOOGL", "AMZN",
    "SMCI", "PLTR", "AI", "CRWD", "DDOG", "SNOW", "COIN", "SHOP", "MELI", "SE",
    "IONQ", "RGTI", "QBTS", "ARRY", "GTLS", "AEHR", "CAMT", "LSCC",
]

_ALL_SECTORS = (
    _IT + _COMM + _CD + _CS + _EN + _FIN + _HC + _IND + _MAT + _UT + _RE
)


def get_scan_universe(extra_watchlist=None):
    seen = set()
    universe = []
    for t in _ALL_SECTORS + (extra_watchlist or []):
        if t and t not in seen:
            seen.add(t)
            universe.append(t)
    return universe
