from flask import Blueprint, request, jsonify, session
import anthropic
import finnhub
from config import Config
from datetime import datetime

watchlist_bp = Blueprint('watchlist', __name__)

# In-memory store (upgrade to DB in Phase 2)
# Structure: { user_id: { "user": [...], "ai": [...], "ai_updated": "..." } }
watchlist_store = {}

_WATCHLIST_TOOL = {
    "name": "submit_watchlist",
    "description": "Submit the final structured AI watchlist",
    "input_schema": {
        "type": "object",
        "required": ["theme", "stocks", "market_note"],
        "properties": {
            "theme":       {"type": "string"},
            "market_note": {"type": "string"},
            "stocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker":   {"type": "string"},
                        "company":  {"type": "string"},
                        "sector":   {"type": "string"},
                        "why":      {"type": "string"},
                        "setup":    {"type": "string"},
                        "risk":     {"type": "string"},
                        "catalyst": {"type": "string"},
                        "learn":    {"type": "string"}
                    }
                }
            }
        }
    }
}


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

    return jsonify({"success": True, "watchlist": watchlist_store[user_id]["user"]})

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
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    user_id    = str(session.get('user_id', 'guest'))
    data       = request.get_json() or {}
    prefs      = data.get('preferences', {})
    risk_level = prefs.get('risk', 'medium')
    sectors    = prefs.get('sectors', [])
    style      = prefs.get('style', 'swing')
    region     = prefs.get('region', 'US')
    today      = datetime.now().strftime('%A, %B %d, %Y')

    ac = get_anthropic_client()

    # ── Call 1: web research (Haiku, cheap) ──────────────────────────────
    research_prompt = (
        f"Today is {today}. You are a quant analyst. "
        f"Search the web for current {region} market conditions and identify 8-10 stocks "
        f"suited for a {style} trader with {risk_level} risk tolerance"
        + (f" interested in {', '.join(sectors)}" if sectors else "") + ". "
        "For each stock provide: ticker, company, sector, why it is relevant today, "
        "technical setup, risk level, upcoming catalyst, and a beginner lesson. "
        "Also summarise the overall market theme and conditions. Use real current data."
    )

    try:
        msg1 = ac.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": research_prompt}]
        )
    except Exception as e:
        return jsonify({"error": f"call1_research: {e}"}), 500

    research = "".join(
        b.text for b in msg1.content if hasattr(b, 'text')
    ).strip()

    if not research:
        return jsonify({"error": "No market data returned from research"}), 500

    # ── Call 2: structured output via tool_choice (Sonnet, reliable JSON) ─
    try:
        msg2 = ac.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            tools=[_WATCHLIST_TOOL],
            tool_choice={"type": "tool", "name": "submit_watchlist"},
            messages=[{
                "role": "user",
                "content": (
                    "Based on this market research, call submit_watchlist "
                    f"with all fields populated:\n\n{research}"
                )
            }]
        )
    except Exception as e:
        return jsonify({"error": f"call2_structure: {e}"}), 500

    result = None
    for block in msg2.content:
        if getattr(block, 'type', None) == 'tool_use':
            result = block.input
            break

    if not result:
        return jsonify({"error": "Structured output not returned"}), 500

    result['generated_at'] = datetime.now().isoformat()

    if user_id not in watchlist_store:
        watchlist_store[user_id] = {"user": [], "ai": [], "ai_updated": None}

    watchlist_store[user_id]["ai"]          = result.get("stocks", [])
    watchlist_store[user_id]["ai_updated"]  = datetime.now().isoformat()
    watchlist_store[user_id]["ai_theme"]    = result.get("theme", "")
    watchlist_store[user_id]["market_note"] = result.get("market_note", "")

    return jsonify(result)
