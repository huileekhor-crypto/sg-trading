from flask import Blueprint, request, jsonify
import anthropic
import finnhub
from config import Config
from datetime import datetime
import json

scanner_bp = Blueprint('scanner', __name__)

# Store last scan result in memory (replaced by DB in Phase 2)
last_scan_cache = {}

@scanner_bp.route('/scanner', methods=['GET'])
def get_market_scan():
    region = request.args.get('region', 'US')
    force  = request.args.get('force', 'false').lower() == 'true'

    # Return cached result if available and not forcing refresh
    cache_key = f"scan_{region}"
    if not force and cache_key in last_scan_cache:
        cached = last_scan_cache[cache_key]
        cached['from_cache'] = True
        return jsonify(cached)

    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    try:
        ac = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        today = datetime.now().strftime('%A, %B %d, %Y')
        sgt_time = datetime.utcnow()

        prompt = f"""Today is {today} SGT. You are a professional market analyst based in Singapore.
Search the web for current market data and provide a comprehensive daily market sentiment report for the {region} market.

Return ONLY a valid JSON object (no markdown, no backticks) with this exact structure:
{{
  "sentiment": {{
    "score": <number 0-100>,
    "label": "<Extremely Bullish|Bullish|Slightly Bullish|Neutral|Slightly Bearish|Bearish|Extremely Bearish>",
    "sublabel": "<one short phrase>",
    "summary": "<2-3 sentences on today's market mood and key drivers>",
    "flags": [
      {{"text": "<flag>", "type": "<green|red|amber|blue>"}}
    ]
  }},
  "macro": {{
    "vix": "<current VIX level and interpretation>",
    "fear_greed": "<current Fear & Greed score and zone>",
    "scenario": "<1|2|3|4|5>",
    "scenario_name": "<Normal Correction|Panic Correction|Extreme Panic|Systemic Risk|Euphoria>",
    "action": "<exact action to take based on scenario>"
  }},
  "stocks": [
    {{
      "ticker": "<TICKER>",
      "name": "<Company Name>",
      "signal": "<LONG|SHORT|WATCH>",
      "conviction": "<High|Medium|Low>",
      "reason": "<2 sentences why in focus today>",
      "tags": ["<momentum|reversal|breakout|earnings|watch>"]
    }}
  ],
  "events": [
    {{
      "time": "<e.g. 8:30AM ET>",
      "impact": "<high|medium|low>",
      "title": "<Event>",
      "detail": "<brief detail>"
    }}
  ]
}}

Rules:
- stocks: 5-7 genuinely worth watching TODAY
- flags: 3-5 short market condition flags
- events: 4-6 key events today
- scenario: match to the 5-scenario framework (1=normal correction, 2=panic, 3=extreme panic, 4=systemic risk, 5=euphoria)
- Base on real current data only"""

        msg = ac.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract text from response
        raw_text = ""
        for block in msg.content:
            if hasattr(block, 'text'):
                raw_text += block.text

        # Parse JSON - strip markdown fences then find outermost object
        import re
        clean = re.sub(r'```(?:json)?\s*', '', raw_text).replace('```', '')
        match = re.search(r'\{[\s\S]*\}', clean)
        if not match:
            return jsonify({"error": "Could not parse market data"}), 500

        json_str = match.group(0)
        # Remove trailing commas before } or ] (common LLM output artifact)
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

        data = json.loads(json_str)
        data['timestamp']  = datetime.now().isoformat()
        data['region']     = region
        data['from_cache'] = False

        # Cache the result
        last_scan_cache[cache_key] = data
        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scanner_bp.route('/scanner/last', methods=['GET'])
def get_last_scan():
    """Return the last cached scan result"""
    region    = request.args.get('region', 'US')
    cache_key = f"scan_{region}"
    if cache_key in last_scan_cache:
        return jsonify(last_scan_cache[cache_key])
    return jsonify({"error": "No scan available yet. Run a scan first."}), 404
