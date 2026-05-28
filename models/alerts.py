import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'users.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_alerts_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            ticker      TEXT NOT NULL,
            target      REAL NOT NULL,
            condition   TEXT NOT NULL,
            fired       INTEGER DEFAULT 0,
            fired_price REAL,
            fired_at    TEXT,
            seen        INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS alert_recipients (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL UNIQUE,
            name       TEXT NOT NULL DEFAULT '',
            active     INTEGER NOT NULL DEFAULT 1,
            added_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS breakout_sent (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker    TEXT NOT NULL,
            sent_at   TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# ── Email recipients ──────────────────────────────────────────────────────────

def get_recipients():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM alert_recipients ORDER BY added_at DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_recipients():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM alert_recipients WHERE active = 1'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_recipient(email, name=''):
    conn = get_db()
    conn.execute(
        'INSERT OR IGNORE INTO alert_recipients (email, name) VALUES (?, ?)',
        (email.strip().lower(), name.strip())
    )
    conn.commit()
    conn.close()


def delete_recipient(recipient_id):
    conn = get_db()
    conn.execute('DELETE FROM alert_recipients WHERE id = ?', (recipient_id,))
    conn.commit()
    conn.close()


def toggle_recipient(recipient_id):
    conn = get_db()
    conn.execute(
        'UPDATE alert_recipients SET active = 1 - active WHERE id = ?',
        (recipient_id,)
    )
    conn.commit()
    conn.close()


# ── Breakout dedup ────────────────────────────────────────────────────────────

def was_recently_alerted(ticker, hours=24):
    conn = get_db()
    row = conn.execute(
        '''SELECT 1 FROM breakout_sent
           WHERE ticker = ?
             AND sent_at > datetime('now', ?)
           LIMIT 1''',
        (ticker.upper(), f'-{hours} hours')
    ).fetchone()
    conn.close()
    return row is not None


def mark_alerted(ticker):
    conn = get_db()
    conn.execute(
        'INSERT INTO breakout_sent (ticker, sent_at) VALUES (?, ?)',
        (ticker.upper(), datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

def add_alert(user_id, ticker, target, condition):
    conn = get_db()
    conn.execute(
        'INSERT INTO alerts (user_id, ticker, target, condition) VALUES (?, ?, ?, ?)',
        (user_id, ticker.upper().strip(), target, condition)
    )
    conn.commit()
    conn.close()

def get_alerts(user_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM alerts WHERE user_id = ? ORDER BY fired ASC, created_at DESC',
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_alert(user_id, alert_id):
    conn = get_db()
    conn.execute('DELETE FROM alerts WHERE id = ? AND user_id = ?', (alert_id, user_id))
    conn.commit()
    conn.close()

def get_active_alerts():
    """All unfired alerts across all users — used by the scheduler."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM alerts WHERE fired = 0').fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fire_alert(alert_id, fired_price):
    conn = get_db()
    conn.execute(
        'UPDATE alerts SET fired=1, fired_price=?, fired_at=? WHERE id=?',
        (round(fired_price, 2), datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), alert_id)
    )
    conn.commit()
    conn.close()

def ack_alerts(user_id):
    """Mark all fired alerts for a user as seen (clears badge)."""
    conn = get_db()
    conn.execute(
        'UPDATE alerts SET seen=1 WHERE user_id=? AND fired=1 AND seen=0',
        (user_id,)
    )
    conn.commit()
    conn.close()

def unseen_count(user_id):
    conn = get_db()
    row = conn.execute(
        'SELECT COUNT(*) FROM alerts WHERE user_id=? AND fired=1 AND seen=0',
        (user_id,)
    ).fetchone()
    conn.close()
    return row[0]
