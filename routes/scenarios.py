from flask import Blueprint, jsonify
from datetime import datetime

scenarios_bp = Blueprint('scenarios', __name__)

SCENARIOS = [
    {
        "id": 1,
        "cls": "s1",
        "title": "Normal Correction",
        "chinese": "正常回调",
        "color": "green",
        "action": "DCA Normally",
        "signals": [
            {"name": "VIX",         "value": "18–25 · Volatility warming"},
            {"name": "Fear & Greed","value": "25–45 · Fear zone"},
            {"name": "Index Drop",  "value": "3–5% pullback"},
            {"name": "Credit (HYG)","value": "Stable · No anomaly"}
        ],
        "actions": [
            {"check": "✅", "text": "Do not panic — this is completely normal"},
            {"check": "✅", "text": "Maintain regular DCA schedule"},
            {"check": "✅", "text": "No need to change strategy"},
            {"check": "✅", "text": "Watch for upgrade to Scenario 2 if drop extends"}
        ],
        "description": "A healthy, normal market correction. Volatility is slightly elevated but credit markets are stable. Continue investing as planned."
    },
    {
        "id": 2,
        "cls": "s2",
        "title": "Panic Correction",
        "chinese": "恐慌回调",
        "color": "cyan",
        "action": "Buy in Tranches",
        "signals": [
            {"name": "VIX",         "value": ">25, approaching 30"},
            {"name": "Fear & Greed","value": "<25 · Extreme fear"},
            {"name": "Index Drop",  "value": "7–10% pullback"},
            {"name": "Credit (HYG)","value": "Holding · USD stable"}
        ],
        "actions": [
            {"check": "✅", "text": "1st 30% → Deploy when VIX crosses 25"},
            {"check": "✅", "text": "2nd 30% → Deploy when VIX hits 30"},
            {"check": "✅", "text": "Final 40% → Deploy after VIX peaks and falls"},
            {"check": "✅", "text": "Confirm HYG not crashing before each tranche"}
        ],
        "description": "A genuine buying opportunity disguised by scary headlines. Credit is still healthy. Deploy capital in a structured 30/30/40 split tied to VIX levels."
    },
    {
        "id": 3,
        "cls": "s3",
        "title": "Extreme Panic",
        "chinese": "极端恐慌",
        "color": "amber",
        "action": "Contrarian Buy",
        "signals": [
            {"name": "VIX",           "value": ">35 or 40 · Extreme"},
            {"name": "Fear & Greed",  "value": "0–15 · Extreme fear"},
            {"name": "AAII Sentiment","value": "Bearish >31% above avg"},
            {"name": "Credit + Banks","value": "Stable · Banks normal"}
        ],
        "actions": [
            {"check": "✅", "text": "Buy core quality assets aggressively"},
            {"check": "✅", "text": "Focus on strong cash-flow companies"},
            {"check": "⚠",  "text": "Do NOT go all-in — retain cash reserve"},
            {"check": "✅", "text": "Scale in — market may drop further before bottoming"}
        ],
        "description": "Historically one of the best buying environments. Extreme fear with stable credit = contrarian opportunity. Buy quality but retain some cash."
    },
    {
        "id": 4,
        "cls": "s4",
        "title": "Systemic Risk",
        "chinese": "系统性风险",
        "color": "red",
        "action": "Defend First",
        "signals": [
            {"name": "VIX",           "value": ">30 rising · No peak"},
            {"name": "Credit Spreads","value": "Rapidly expanding"},
            {"name": "HYG / JNK",     "value": "Crashing · USD spiking"},
            {"name": "Bank Stocks",   "value": "Crashing · Liquidity odd"}
        ],
        "actions": [
            {"check": "🚫", "text": "DO NOT buy the dip — this is not Scenario 2"},
            {"check": "✅", "text": "Reduce leverage immediately"},
            {"check": "✅", "text": "Cut high-beta and volatile positions"},
            {"check": "✅", "text": "Move to cash — wait for credit to stabilise"}
        ],
        "description": "The financial system itself is under stress. Credit markets breaking = do not catch this falling knife. Preserve capital and wait."
    },
    {
        "id": 5,
        "cls": "s5",
        "title": "Euphoria",
        "chinese": "泡沫贪婪",
        "color": "purple",
        "action": "Trim & Build Cash",
        "signals": [
            {"name": "VIX",          "value": "<15 · Nobody buying insurance"},
            {"name": "Fear & Greed", "value": ">75 · Extreme greed"},
            {"name": "Retail Signal","value": "Non-investors giving tips"},
            {"name": "Market",       "value": "Everyone confident · ATH"}
        ],
        "actions": [
            {"check": "✅", "text": "Trim oversized positions gradually"},
            {"check": "✅", "text": "Sell covered calls to generate yield"},
            {"check": "✅", "text": "Build cash reserves for next Scenario 2/3"},
            {"check": "⚠",  "text": "Do not short — euphoria lasts longer than logic"}
        ],
        "description": "Risk/reward has flipped. Nobody fears downside, retail is euphoric. Reduce exposure and build the cash you will deploy when fear returns."
    }
]

@scenarios_bp.route('/scenarios', methods=['GET'])
def get_scenarios():
    return jsonify({
        "scenarios": SCENARIOS,
        "key_rule": "The signal that separates a buying opportunity from a trap is always the credit market. If HYG/JNK stable while stocks fall = Scenario 2/3. If HYG/JNK also crashing = Scenario 4.",
        "timestamp": datetime.now().isoformat()
    })
