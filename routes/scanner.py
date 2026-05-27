from flask import Blueprint, request, jsonify
import anthropic
import finnhub
from config import Config
from datetime import datetime

scanner_bp = Blueprint('scanner', __name__)

last_scan_cache = {}

# Tool schema used to force structured output on the second API call.
# tool_choice={"type":"tool"} guarantees block.input is valid JSON — no text parsing.
_REPORT_TOOL = {
    "name": "submit_market_report",
    "description": "Submit the final structured market report",
    "input_schema": {
        "type": "object",
        "required": ["sentiment", "macro", "stocks", "events"],
        "properties": {
            "sentiment": {
                "type": "object",
                "required": ["score", "label", "sublabel", "summary", "flags"],
                "properties": {
                    "score":    {"type": "number"},
                    "label":    {"type": "string"},
                    "sublabel": {"type": "string"},
                    "summary":  {"type": "string"},
                    "flags": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "type": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "macro": {
                "type": "object",
                "required": ["vix", "fear_greed", "scenario", "scenario_name", "action"],
                "properties": {
                    "vix":           {"type": "string"},
                    "fear_greed":    {"type": "string"},
                    "scenario":      {"type": "string"},
                    "scenario_name": {"type": "string"},
                    "action":        {"type": "string"}
                }
            },
            "stocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker":     {"type": "string"},
                        "name":       {"type": "string"},
                        "signal":     {"type": "string"},
                        "conviction": {"type": "string"},
                        "reason":     {"type": "string"},
                        "tags":       {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "time":   {"type": "string"},
                        "impact": {"type": "string"},
                        "title":  {"type": "string"},
                        "detail": {"type": "string"}
                    }
                }
            }
        }
    }
}


@scanner_bp.route('/scanner', methods=['GET'])
def get_market_scan():
    region = request.args.get('region', 'US')
    force  = request.args.get('force', 'false').lower() == 'true'

    cache_key = f"scan_{region}"
    if not force and cache_key in last_scan_cache:
        cached = last_scan_cache[cache_key]
        cached['from_cache'] = True
        return jsonify(cached)

    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    try:
        ac    = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        today = datetime.now().strftime('%A, %B %d, %Y')

        # ── Call 1: web research ──────────────────────────────────────────
        research_prompt = (
            f"Today is {today} SGT. You are a professional market analyst in Singapore. "
            f"Search the web for live {region} market data and write a concise analyst summary covering: "
            "current market sentiment score (0-100) and label, VIX level, CNN Fear & Greed index, "
            "the market scenario (1=normal correction, 2=panic, 3=extreme panic, 4=systemic risk, 5=euphoria), "
            "5-7 stocks worth watching today with signal and reason, "
            "and 4-6 key economic events today. Use real current numbers."
        )

        msg1 = ac.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": research_prompt}]
        )

        research = "".join(
            block.text for block in msg1.content if hasattr(block, 'text')
        ).strip()

        if not research:
            return jsonify({"error": "No market data returned from research"}), 500

        # ── Call 2: force structured output via tool_use ──────────────────
        # tool_choice guarantees the model calls submit_market_report,
        # so block.input is already a valid Python dict — zero JSON parsing.
        msg2 = ac.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            tools=[_REPORT_TOOL],
            tool_choice={"type": "tool", "name": "submit_market_report"},
            messages=[{
                "role": "user",
                "content": (
                    f"Based on this market research, call submit_market_report "
                    f"with all fields populated:\n\n{research}"
                )
            }]
        )

        data = None
        for block in msg2.content:
            if getattr(block, 'type', None) == 'tool_use':
                data = block.input
                break

        if not data:
            return jsonify({"error": "Structured output not returned"}), 500

        data['timestamp']  = datetime.now().isoformat()
        data['region']     = region
        data['from_cache'] = False

        last_scan_cache[cache_key] = data
        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scanner_bp.route('/scanner/last', methods=['GET'])
def get_last_scan():
    region    = request.args.get('region', 'US')
    cache_key = f"scan_{region}"
    if cache_key in last_scan_cache:
        return jsonify(last_scan_cache[cache_key])
    return jsonify({"error": "No scan available yet. Run a scan first."}), 404
