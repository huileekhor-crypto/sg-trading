"""
Unusual Whales WebSocket live streaming.
Channels: price, flow_alerts, off_lit_trades (dark pool), news.
Falls back to Yahoo Finance polling if WebSocket unavailable.
"""

import os
import json
import time
import threading
import queue
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# ─── State ────────────────────────────────────────────────────────────────────
_ws_state = {
    "connected": False,
    "source":    "Yahoo",       # "UW" or "Yahoo"
    "status_label": "⚡ LIVE (Yahoo)",
    "last_ping":  0,
    "error":      None,
}

_price_store   = {}   # ticker → {price, change_pct, ts}
_flow_alerts   = []   # last 50 flow alerts
_darkpool_feed = []   # last 50 dark pool prints
_news_feed     = []   # last 20 news items
_subscribers   = defaultdict(list)   # event_type → [queues]
_ws_thread     = None
_ws_lock       = threading.Lock()

RECONNECT_DELAY = 10   # seconds between reconnect attempts
MAX_RECONNECTS  = 999  # effectively unlimited
_stop_flag      = threading.Event()


# ─── Public API ───────────────────────────────────────────────────────────────

def get_status():
    return {
        "connected":    _ws_state["connected"],
        "source":       _ws_state["source"],
        "status_label": _ws_state["status_label"],
        "error":        _ws_state["error"],
        "prices_cached": len(_price_store),
        "flow_count":   len(_flow_alerts),
    }


def get_live_price_ws(ticker):
    """Get price from WS cache, fallback to Yahoo."""
    cached = _price_store.get(ticker.upper())
    if cached and time.time() - cached.get("ts", 0) < 30:
        return cached
    # Yahoo fallback
    from utils.prices import get_live_price
    result = get_live_price(ticker)
    if result and result.get("price"):
        _price_store[ticker.upper()] = {**result, "ts": time.time()}
    return result


def get_recent_flow_alerts(ticker=None, limit=20):
    alerts = _flow_alerts[-limit:]
    if ticker:
        alerts = [a for a in alerts if a.get("ticker", "").upper() == ticker.upper()]
    return alerts


def get_recent_darkpool(ticker=None, limit=20):
    prints = _darkpool_feed[-limit:]
    if ticker:
        prints = [p for p in prints if p.get("ticker", "").upper() == ticker.upper()]
    return prints


def get_recent_news(limit=10):
    return _news_feed[-limit:]


def subscribe(event_type):
    """Return a Queue that receives pushed events for this type."""
    q = queue.Queue(maxsize=50)
    with _ws_lock:
        _subscribers[event_type].append(q)
    return q


def unsubscribe(event_type, q):
    with _ws_lock:
        try:
            _subscribers[event_type].remove(q)
        except ValueError:
            pass


def start_websocket(watchlist=None):
    """Start the WebSocket background thread. Call once at startup."""
    global _ws_thread
    _stop_flag.clear()
    if _ws_thread and _ws_thread.is_alive():
        return
    _ws_thread = threading.Thread(
        target=_ws_loop,
        args=(watchlist or [],),
        daemon=True,
        name="UW-WebSocket"
    )
    _ws_thread.start()
    log.info("UW WebSocket thread started")


def stop_websocket():
    _stop_flag.set()


# ─── WebSocket loop ───────────────────────────────────────────────────────────

def _ws_loop(watchlist):
    """Main reconnect loop."""
    uw_key = os.environ.get("UW_API_KEY", "")
    attempts = 0

    while not _stop_flag.is_set() and attempts < MAX_RECONNECTS:
        if not uw_key:
            # No key — stay in Yahoo polling mode
            _set_status(connected=False, source="Yahoo",
                        label="⚡ LIVE (Yahoo)", error="UW_API_KEY not set")
            _yahoo_poll_loop(watchlist)
            return

        try:
            _set_status(connected=False, source="Yahoo", label="⟳ Connecting to UW...")
            _connect_uw(uw_key, watchlist)
        except Exception as e:
            attempts += 1
            err = str(e)[:80]
            _set_status(connected=False, source="Yahoo",
                        label="⚡ LIVE (Yahoo)", error=f"WS error: {err}")
            log.warning(f"WS connection failed ({attempts}): {err}")
            _yahoo_poll_loop(watchlist, duration=RECONNECT_DELAY)

    log.info("WS loop exited")


def _connect_uw(uw_key, watchlist):
    """Attempt to connect to UW WebSocket. Raises on failure."""
    try:
        import websocket
    except ImportError:
        raise RuntimeError("websocket-client not installed — using Yahoo fallback")

    ws_url = f"wss://api.unusualwhales.com/ws?token={uw_key}"
    channels = ["flow_alerts", "off_lit_trades", "news"]
    if watchlist:
        channels += [f"price:{t}" for t in watchlist[:20]]

    connected_event = threading.Event()
    error_holder    = [None]

    def on_open(ws):
        _set_status(connected=True, source="UW", label="⚡ LIVE (UW)")
        # Subscribe to channels
        for ch in channels:
            ws.send(json.dumps({"action": "subscribe", "channel": ch}))
        connected_event.set()
        log.info("UW WS connected")

    def on_message(ws, msg):
        try:
            data = json.loads(msg)
            ch   = data.get("channel", data.get("type", ""))
            _handle_message(ch, data)
        except Exception:
            pass

    def on_error(ws, err):
        error_holder[0] = err
        _set_status(connected=False, source="Yahoo", label="⚡ LIVE (Yahoo)",
                    error=str(err)[:80])

    def on_close(ws, code, msg):
        _set_status(connected=False, source="Yahoo", label="⚡ LIVE (Yahoo)")
        log.info(f"UW WS closed: {code} {msg}")

    ws_app = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # Run in blocking mode — exits when closed or errored
    ws_app.run_forever(ping_interval=30, ping_timeout=10)

    if error_holder[0]:
        raise RuntimeError(str(error_holder[0]))


def _yahoo_poll_loop(watchlist, duration=None):
    """Poll Yahoo every ~8s for prices while WS is down."""
    from utils.prices import get_live_price
    start = time.time()
    while not _stop_flag.is_set():
        if duration and time.time() - start >= duration:
            return
        for ticker in (watchlist or []):
            if _stop_flag.is_set():
                return
            try:
                pd = get_live_price(ticker)
                if pd and pd.get("price"):
                    _price_store[ticker.upper()] = {**pd, "ts": time.time()}
                    _push("price", {"ticker": ticker.upper(), **pd})
            except Exception:
                pass
            time.sleep(0.3)
        time.sleep(8)


# ─── Message handlers ─────────────────────────────────────────────────────────

def _handle_message(channel, data):
    payload = data.get("data", data)

    if "price" in channel:
        ticker = (channel.split(":")[-1] if ":" in channel
                  else payload.get("ticker", "")).upper()
        if ticker:
            entry = {
                "ticker":      ticker,
                "price":       _sf(payload.get("price") or payload.get("last_price")),
                "change_pct":  _sf(payload.get("change_pct") or payload.get("percent_change")),
                "volume":      _sf(payload.get("volume", 0)),
                "ts":          time.time(),
            }
            _price_store[ticker] = entry
            _push("price", entry)

    elif "flow" in channel:
        item = {
            "ticker":    str(payload.get("ticker", "")).upper(),
            "put_call":  payload.get("put_call", ""),
            "premium":   _sf(payload.get("premium", 0)),
            "sentiment": payload.get("sentiment", ""),
            "strike":    payload.get("strike", ""),
            "expiry":    payload.get("expiry", ""),
            "ts":        time.time(),
        }
        _flow_alerts.append(item)
        if len(_flow_alerts) > 200:
            _flow_alerts.pop(0)
        _push("flow_alert", item)

    elif "off_lit" in channel or "darkpool" in channel:
        item = {
            "ticker": str(payload.get("ticker", "")).upper(),
            "size":   _sf(payload.get("size") or payload.get("notional_value", 0)),
            "price":  _sf(payload.get("price", 0)),
            "ts":     time.time(),
        }
        _darkpool_feed.append(item)
        if len(_darkpool_feed) > 200:
            _darkpool_feed.pop(0)
        _push("darkpool", item)

    elif "news" in channel:
        item = {
            "headline": payload.get("headline", payload.get("title", "")),
            "ticker":   str(payload.get("ticker", "")).upper(),
            "source":   payload.get("source", ""),
            "ts":       time.time(),
        }
        _news_feed.append(item)
        if len(_news_feed) > 100:
            _news_feed.pop(0)
        _push("news", item)


def _push(event_type, data):
    with _ws_lock:
        queues = _subscribers.get(event_type, [])
        dead   = []
        for q in queues:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            queues.remove(q)


def _set_status(connected, source, label, error=None):
    _ws_state["connected"]    = connected
    _ws_state["source"]       = source
    _ws_state["status_label"] = label
    _ws_state["error"]        = error
    _ws_state["last_ping"]    = time.time()


def _sf(val):
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0
