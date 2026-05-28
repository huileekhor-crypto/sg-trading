import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'users.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_journal_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            ticker        TEXT NOT NULL,
            trade_date    TEXT NOT NULL,
            entry_price   REAL NOT NULL,
            exit_price    REAL NOT NULL,
            position_size REAL NOT NULL,
            setup_type    TEXT DEFAULT 'Other',
            emotion       INTEGER DEFAULT 3,
            notes         TEXT DEFAULT '',
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_trade(user_id, ticker, trade_date, entry_price, exit_price,
              position_size, setup_type, emotion, notes):
    conn = get_db()
    conn.execute('''
        INSERT INTO trades
          (user_id, ticker, trade_date, entry_price, exit_price,
           position_size, setup_type, emotion, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, ticker.upper().strip(), trade_date,
          entry_price, exit_price, position_size,
          setup_type, emotion, notes))
    conn.commit()
    conn.close()

def get_trades(user_id, ticker=None, date_from=None, date_to=None):
    conn = get_db()
    q      = 'SELECT * FROM trades WHERE user_id = ?'
    params = [user_id]
    if ticker:
        q += ' AND ticker = ?'
        params.append(ticker.upper().strip())
    if date_from:
        q += ' AND trade_date >= ?'
        params.append(date_from)
    if date_to:
        q += ' AND trade_date <= ?'
        params.append(date_to)
    q += ' ORDER BY trade_date DESC, id DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_trade(user_id, trade_id):
    conn = get_db()
    conn.execute('DELETE FROM trades WHERE id = ? AND user_id = ?',
                 (trade_id, user_id))
    conn.commit()
    conn.close()
