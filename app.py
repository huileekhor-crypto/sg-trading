import os
from flask import Flask, jsonify, request, session, send_from_directory, redirect, render_template
from flask_cors import CORS
from routes.screener import screener_bp
from routes.scanner import scanner_bp
from routes.scenarios import scenarios_bp
from routes.chart import chart_bp
from routes.auth import auth_bp
from routes.watchlist import watchlist_bp
from routes.journal import journal_bp
from routes.alerts import alerts_bp
from models.user import init_db
from models.journal import init_journal_db
from models.alerts import init_alerts_db
from scheduler import start_scheduler

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Secret key for sessions — set in Azure Application Settings
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-azure-settings')
app.config['SESSION_COOKIE_SECURE']   = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Register blueprints
app.register_blueprint(screener_bp,  url_prefix='/api')
app.register_blueprint(scanner_bp,   url_prefix='/api')
app.register_blueprint(scenarios_bp, url_prefix='/api')
app.register_blueprint(chart_bp,     url_prefix='/api')
app.register_blueprint(auth_bp)
app.register_blueprint(watchlist_bp, url_prefix='/api')
app.register_blueprint(journal_bp,   url_prefix='/api')
app.register_blueprint(alerts_bp,   url_prefix='/api')

def login_required(f):
    """Decorator to protect routes"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

# ===== ROUTES =====

@app.route('/')
def index():
    """Login page — public"""
    if 'user_id' in session:
        return redirect('/dashboard')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard — protected"""
    return send_from_directory('static', 'index.html')

@app.route('/api/<path:path>', methods=['GET','POST','PUT','DELETE'])
def api_protected(path):
    """All API routes require login"""
    if 'user_id' not in session:
        return jsonify({"error": "Authentication required"}), 401
    return jsonify({"error": "Route not found"}), 404

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "user": session.get('user_name', 'not logged in')
    })

init_db()
init_journal_db()
init_alerts_db()
start_scheduler()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
