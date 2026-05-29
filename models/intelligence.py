import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'intelligence.db')


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_intelligence_db():
    conn = _db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS intelligence_scans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at      TEXT NOT NULL,
            catalysts   TEXT,
            setups      TEXT,
            sector_heat TEXT,
            summary     TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def save_scan(run_at, catalysts, setups, sector_heat, summary=''):
    conn = _db()
    conn.execute(
        'INSERT INTO intelligence_scans (run_at, catalysts, setups, sector_heat, summary) VALUES (?,?,?,?,?)',
        (run_at, json.dumps(catalysts), json.dumps(setups), json.dumps(sector_heat), summary)
    )
    conn.commit()
    conn.close()


def get_latest():
    conn = _db()
    row  = conn.execute('SELECT * FROM intelligence_scans ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    if not row:
        return None
    return {
        'id':          row['id'],
        'run_at':      row['run_at'],
        'catalysts':   json.loads(row['catalysts']   or '[]'),
        'setups':      json.loads(row['setups']      or '[]'),
        'sector_heat': json.loads(row['sector_heat'] or '{}'),
        'summary':     row['summary'] or '',
        'created_at':  row['created_at'],
    }
