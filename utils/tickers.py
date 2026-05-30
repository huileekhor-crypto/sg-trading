# Curated universe: S&P 500 large-caps + NASDAQ 100 + AI/semi/tech focus
# ~200 tickers covering quality names for the scanner

SP500_TICKERS = [
    # Mega-cap tech
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","ORCL","CRM",
    # AI / semiconductors (core edge)
    "AMD","MU","INTC","QCOM","TXN","AMAT","LRCX","KLAC","MRVL","SMCI",
    "ARM","TSM","ASML","CDNS","SNPS","MPWR","ON","WOLF","SWKS","QRVO",
    # Software / cloud
    "NOW","ADBE","INTU","TEAM","DDOG","ZS","CRWD","PANW","FTNT","OKTA",
    "MDB","SNOW","PLTR","PATH","AI","GTLB","S","NET","CFLT","HUBS",
    # Consumer / e-commerce
    "SHOP","MELI","SE","BABA","JD","PDD","TEMU","W","ETSY","EBAY",
    # Healthcare / biotech
    "LLY","NVO","MRNA","BNTX","REGN","GILD","AMGN","ABBV","BMY","PFE",
    "ISRG","SYK","MDT","BSX","EW","DXCM","IDXX","ILMN","VEEV","IQV",
    # Financials
    "JPM","BAC","GS","MS","C","WFC","BLK","SCHW","AXP","COF","V","MA",
    # Energy / commodities
    "XOM","CVX","COP","SLB","HAL","OXY","DVN","FANG","MRO","APA",
    # Consumer staples / discretionary
    "WMT","COST","TGT","HD","LOW","NKE","SBUX","MCD","DPZ","YUM",
    # Industrials / defense
    "BA","LMT","RTX","NOC","GD","CAT","DE","EMR","HON","MMM",
    # Communication
    "DIS","NFLX","CMCSA","CHTR","T","VZ","WBD","PARA","FOXA","SNAP",
    # Other momentum names
    "COIN","HOOD","RBLX","U","UNITY","LYFT","UBER","ABNB","DASH","PINS",
    "TWLO","BILL","PAYC","ADP","PAYX","FISV","FIS","GPN","SQ","PYPL",
    # Small/mid cap AI edge (watchlist)
    "NBIS","SMCI","IONQ","ARRY","GTLS","AEHR","WOLF","CAMT","LSCC",
]

NDX100_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","TSLA","AVGO","COST",
    "NFLX","AMD","QCOM","AMAT","MRVL","ARM","LRCX","PANW","KLAC","SNPS",
    "CDNS","ADI","MCHP","NXPI","ON","CRWD","FTNT","ZS","OKTA","DDOG",
    "SNOW","MNST","FANG","FAST","PCAR","ODFL","VRSK","MELI","TEAM","WDAY",
    "ADSK","ANSS","IDXX","ROST","CSGP","SGEN","REGN","AMGN","GILD","BIIB",
    "MDLZ","KHC","SBUX","TMUS","CMCSA","AEP","XEL","CEG","EXC","PEP",
    "ASML","BKNG","ABNB","CSX","CPRT","ORLY","AZN","HON","PAYX","CHTR",
]

WATCHLIST_DEFAULT = [
    "NBIS","MU","NVDA","AMD","MSFT","AAPL","TSLA","META","GOOGL","AMZN",
    "SMCI","PLTR","AI","CRWD","DDOG","SNOW","COIN","SHOP","MELI","SE",
]

def get_scan_universe(extra_watchlist=None):
    seen = set()
    universe = []
    for t in SP500_TICKERS + NDX100_TICKERS + (extra_watchlist or []):
        if t not in seen:
            seen.add(t)
            universe.append(t)
    return universe
