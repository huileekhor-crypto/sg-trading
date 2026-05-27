from flask import Blueprint, request, jsonify, session
import anthropic
import finnhub
from config import Config
from datetime import datetime
import json, re

watchlist_bp = Blueprint('watchlist', __name__)

# In-memory store (upgrade to DB in Phase 2)
# Structure: { user_id: { "user": [...], "ai": [...], "ai_updated": "..." } }
watchlist_store = {}

def get_finnhub_client():
    return finnhub.Client(api_key=Config.FINNHUB_API_KEY)

def get_anthropic_client():
    return anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

# ===== USER WATCHLIST =====

@watchlist_bp.route('/watchlist', methods=['GET'])
def get_watchlist():
    user_id = str(session.get('user_id', 'guest'))
    store   = watchlist_store.get(user_id, {"user": [], "ai": [], "ai_updated": None})
    return jsonify(store)

@watchlist_bp.route('/watchlist/add', methods=['POST'])
def add_to_watchlist():
    user_id = str(session.get('user_id', 'guest'))
    data    = request.get_json()
    ticker  = data.get('ticker', '').upper().strip()

    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400

    if user_id not in watchlist_store:
        watchlist_store[user_id] = {"user": [], "ai": [], "ai_updated": None}

    if ticker not in watchlist_store[user_id]["user"]:
        watchlist_store[user_id]["user"].append(ticker)

    return jsonify({
        "success": True,
        "watchlist": watchlist_store[user_id]["user"]
    })

@watchlist_bp.route('/watchlist/remove', methods=['POST'])
def remove_from_watchlist():
    user_id = str(session.get('user_id', 'guest'))
    data    = request.get_json()
    ticker  = data.get('ticker', '').upper().strip()

    if user_id in watchlist_store and ticker in watchlist_store[user_id]["user"]:
        watchlist_store[user_id]["user"].remove(ticker)

    return jsonify({
        "success": True,
        "watchlist": watchlist_store.get(user_id, {}).get("user", [])
    })

# ===== AI WATCHLIST =====

@watchlist_bp.route('/watchlist/ai-generate', methods=['POST'])
def generate_ai_watchlist():
    """AI generates a personalised watchlist based on market conditions"""
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    user_id = str(session.get('user_id', 'guest'))
    data    = request.get_json() or {}
    prefs   = data.get('preferences', {})

    # Get user preferences
    risk_level = prefs.get('risk', 'medium')       # low/medium/high
    sectors    = prefs.get('sectors', [])            # e.g. ["AI", "Quantum"]
    style      = prefs.get('style', 'swing')         # swing/momentum/value
    region     = prefs.get('region', 'US')

    today = datetime.now().strftime('%A, %B %d, %Y')

    prompt = f"""Today is {today}. You are a professional quant analyst building a personalised stock watchlist.

User preferences:
- Risk level: {risk_level}
- Preferred sectors: {', '.join(sectors) if sectors else 'Any'}
- Trading style: {style}
- Region: {region}

Search the web for current market conditions and generate a watchlist of 8-10 stocks.

Return ONLY valid JSON (no markdown, no backticks):
{{
  "theme": "<one line describing today's market opportunity>",
  "generated_at": "{today}",
  "stocks": [
    {{
      "ticker": "<TICKER>",
      "company": "<Company Name>",
      "sector": "<Sector>",
      "why": "<2 sentences: why this stock belongs on the watchlist TODAY>",
      "setup": "<technical setup in plain English>",
      "risk": "<low|medium|high>",
      "catalyst": "<upcoming catalyst or reason for momentum>",
      "learn": "<one thing a beginner can learn from this stock right now>"
    }}
  ],
  "market_note": "<2 sentences on current market conditions affecting these picks>"
}}

Rules:
- Mix risk levels unless user specified
- Include at least 2 stocks with clear technical setups
- Base on real current data from web search
- Make explanations simple enough for a beginner"""

    try:
        ac = get_anthropic_client()
        msg = ac.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        raw = "".join(b.text for b in msg.content if hasattr(b, 'text'))
        match = re.search(r'\{[\s\S]*\}', raw)
        if not match:
            return jsonify({"error": "Could not generate watchlist"}), 500

        result = json.loads(match.group(0))
        result['generated_at'] = datetime.now().isoformat()

        # Save to store
        if user_id not in watchlist_store:
            watchlist_store[user_id] = {"user": [], "ai": [], "ai_updated": None}

        watchlist_store[user_id]["ai"]         = result.get("stocks", [])
        watchlist_store[user_id]["ai_updated"] = datetime.now().isoformat()
        watchlist_store[user_id]["ai_theme"]   = result.get("theme", "")
        watchlist_store[user_id]["market_note"]= result.get("market_note", "")

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
