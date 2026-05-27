import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'users.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create users table if not exists"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT UNIQUE NOT NULL,
            name        TEXT,
            password    TEXT,
            google_id   TEXT,
            avatar      TEXT,
            provider    TEXT DEFAULT 'email',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login  TEXT
        )
    ''')
    conn.commit()
    conn.close()

def hash_password(password):
    salt = os.urandom(32)
    key  = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return salt.hex() + ':' + key.hex()

def verify_password(stored, provided):
    try:
        salt_hex, key_hex = stored.split(':')
        salt = bytes.fromhex(salt_hex)
        key  = hashlib.pbkdf2_hmac('sha256', provided.encode(), salt, 100000)
        return key.hex() == key_hex
    except:
        return False

def create_user(email, name, password=None, google_id=None, avatar=None, provider='email'):
    conn = get_db()
    try:
        hashed = hash_password(password) if password else None
        conn.execute('''
            INSERT INTO users (email, name, password, google_id, avatar, provider)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email.lower(), name, hashed, google_id, avatar, provider))
        conn.commit()
        return get_user_by_email(email)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_email(email):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_google_id(google_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE google_id = ?', (google_id,)).fetchone()
    conn.close()
    return dict(user) if user else None

def update_last_login(user_id):
    conn = get_db()
    conn.execute('UPDATE users SET last_login = ? WHERE id = ?',
                 (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()
