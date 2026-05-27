from flask import Blueprint, request, jsonify, session, redirect, url_for
from models.user import (create_user, get_user_by_email, get_user_by_id,
                          get_user_by_google_id, verify_password, update_last_login)
import requests
import os

auth_bp = Blueprint('auth', __name__)

# -------------------------------------------------------
# Set these in Azure Portal → Application Settings:
# GOOGLE_CLIENT_ID     = your Google OAuth client ID
# GOOGLE_CLIENT_SECRET = your Google OAuth client secret
# SECRET_KEY           = any random long string
# -------------------------------------------------------

def get_google_config():
    return {
        "client_id":     os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri":  os.environ.get("GOOGLE_REDIRECT_URI",
                         "http://localhost:8000/auth/google/callback")
    }

# ===== EMAIL SIGNUP =====
@auth_bp.route('/auth/signup', methods=['POST'])
def signup():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    name  = data.get('name', '').strip()
    pwd   = data.get('password', '')

    if not email or not name or not pwd:
        return jsonify({"error": "Email, name and password are required"}), 400
    if len(pwd) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if get_user_by_email(email):
        return jsonify({"error": "Email already registered"}), 409

    user = create_user(email, name, password=pwd, provider='email')
    if not user:
        return jsonify({"error": "Could not create account"}), 500

    session['user_id']   = user['id']
    session['user_name'] = user['name']
    session['user_email']= user['email']
    session['avatar']    = user.get('avatar', '')
    update_last_login(user['id'])
    return jsonify({"success": True, "user": {"name": user['name'], "email": user['email']}})

# ===== EMAIL LOGIN =====
@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    pwd   = data.get('password', '')

    user = get_user_by_email(email)
    if not user or user.get('provider') != 'email':
        return jsonify({"error": "Invalid email or password"}), 401
    if not verify_password(user['password'], pwd):
        return jsonify({"error": "Invalid email or password"}), 401

    session['user_id']    = user['id']
    session['user_name']  = user['name']
    session['user_email'] = user['email']
    session['avatar']     = user.get('avatar', '')
    update_last_login(user['id'])
    return jsonify({"success": True, "user": {"name": user['name'], "email": user['email']}})

# ===== GOOGLE OAUTH =====
@auth_bp.route('/auth/google')
def google_login():
    cfg = get_google_config()
    if not cfg['client_id']:
        return jsonify({"error": "Google OAuth not configured. Add GOOGLE_CLIENT_ID to Azure settings."}), 500

    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={cfg['client_id']}"
        f"&redirect_uri={cfg['redirect_uri']}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        "&access_type=offline"
    )
    return redirect(google_auth_url)

@auth_bp.route('/auth/google/callback')
def google_callback():
    code = request.args.get('code')
    if not code:
        return redirect('/?error=google_cancelled')

    cfg = get_google_config()

    # Exchange code for token
    token_res = requests.post('https://oauth2.googleapis.com/token', data={
        'code':          code,
        'client_id':     cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'redirect_uri':  cfg['redirect_uri'],
        'grant_type':    'authorization_code'
    })

    if not token_res.ok:
        return redirect('/?error=google_token_failed')

    token_data   = token_res.json()
    access_token = token_data.get('access_token')

    # Get user info from Google
    userinfo_res = requests.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        headers={'Authorization': f'Bearer {access_token}'}
    )

    if not userinfo_res.ok:
        return redirect('/?error=google_userinfo_failed')

    info      = userinfo_res.json()
    google_id = info.get('sub')
    email     = info.get('email', '').lower()
    name      = info.get('name', email.split('@')[0])
    avatar    = info.get('picture', '')

    # Find or create user
    user = get_user_by_google_id(google_id)
    if not user:
        user = get_user_by_email(email)
        if not user:
            user = create_user(email, name, google_id=google_id,
                               avatar=avatar, provider='google')
        if not user:
            return redirect('/?error=account_creation_failed')

    session['user_id']    = user['id']
    session['user_name']  = user['name']
    session['user_email'] = user['email']
    session['avatar']     = avatar or user.get('avatar', '')
    update_last_login(user['id'])
    return redirect('/dashboard')

# ===== LOGOUT =====
@auth_bp.route('/auth/logout')
def logout():
    session.clear()
    return redirect('/')

# ===== SESSION CHECK =====
@auth_bp.route('/auth/me')
def me():
    if 'user_id' not in session:
        return jsonify({"authenticated": False}), 401
    user = get_user_by_id(session['user_id'])
    if not user:
        session.clear()
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "user": {
            "id":     user['id'],
            "name":   user['name'],
            "email":  user['email'],
            "avatar": session.get('avatar', ''),
            "provider": user.get('provider', 'email')
        }
    })
