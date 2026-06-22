import os
from flask import Flask, jsonify, request, session, redirect, render_template, Response
from flask_cors import CORS
from routes.auth import auth_bp
from routes.scanner import scanner_bp
from routes.analyse import analyse_bp
from routes.manage import manage_bp
from routes.journal import journal_bp
from routes.backtest import backtest_bp
from routes.breakout import breakout_bp
from routes.movers import movers_bp
from routes.setups import setups_bp
from routes.settings import settings_bp
from models.user import init_db
from models.journal import init_journal_db
from scheduler import start_scheduler

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-azure-settings')
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.register_blueprint(auth_bp)
app.register_blueprint(scanner_bp)
app.register_blueprint(analyse_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(journal_bp)
app.register_blueprint(backtest_bp)
app.register_blueprint(breakout_bp)
app.register_blueprint(movers_bp)
app.register_blueprint(setups_bp)
app.register_blueprint(settings_bp)


def login_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/')
        return f(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/movers')
    return render_template('login.html')


@app.route('/dashboard')
@login_required
def dashboard():
    return redirect('/movers')


@app.before_request
def require_login():
    public = ('/', '/auth/login', '/auth/signup', '/auth/google',
              '/auth/google/callback', '/health')
    if request.path in public:
        return
    if request.path.startswith('/static/'):
        return
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({"error": "Authentication required"}), 401
        return redirect('/')


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Not found"}), 404
    return render_template('404.html'), 404


@app.route('/health')
def health():
    return jsonify({"status": "ok", "user": session.get('user_name', 'anonymous')})


@app.route('/api/ws/status')
def ws_status():
    from utils.uw_websocket import get_status
    return jsonify(get_status())


@app.route('/api/ws/price/<ticker>')
def ws_price(ticker):
    from utils.uw_websocket import get_live_price_ws
    return jsonify(get_live_price_ws(ticker.upper()))


@app.route('/api/ws/flow-alerts')
def ws_flow_alerts():
    from utils.uw_websocket import get_recent_flow_alerts
    ticker = request.args.get('ticker')
    return jsonify(get_recent_flow_alerts(ticker=ticker, limit=20))


@app.route('/api/ws/darkpool')
def ws_darkpool():
    from utils.uw_websocket import get_recent_darkpool
    ticker = request.args.get('ticker')
    return jsonify(get_recent_darkpool(ticker=ticker, limit=20))


@app.route('/api/live/price/<ticker>')
def live_price(ticker):
    """SSE endpoint — push live price updates every second."""
    import time
    from utils.uw_websocket import get_live_price_ws
    import json

    def generate():
        for _ in range(60):  # max 60 seconds per connection
            pd = get_live_price_ws(ticker.upper())
            yield f"data: {json.dumps(pd)}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


init_db()
init_journal_db()
start_scheduler()

# Start WS in background (non-blocking, graceful if websocket-client not installed)
try:
    from utils.uw_websocket import start_websocket
    from utils.tickers import WATCHLIST_DEFAULT
    start_websocket(watchlist=WATCHLIST_DEFAULT)
except Exception as _ws_err:
    print(f"WS start skipped: {_ws_err}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
