"""Trades, positions, scan results, and settings database."""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'trading.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_journal_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            mode        TEXT DEFAULT 'SWING',
            direction   TEXT DEFAULT 'LONG',
            entry_price REAL,
            exit_price  REAL,
            shares      INTEGER,
            pnl         REAL,
            pnl_pct     REAL,
            stop        REAL,
            target      REAL,
            score       INTEGER,
            notes       TEXT,
            outcome     TEXT,
            date_open   TEXT,
            date_close  TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS positions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            mode        TEXT DEFAULT 'SWING',
            direction   TEXT DEFAULT 'LONG',
            entry_price REAL,
            shares      INTEGER,
            stop        REAL,
            target      REAL,
            score       INTEGER,
            notes       TEXT,
            uw_notes    TEXT,
            date_open   TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scan_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT,
            score       INTEGER,
            verdict     TEXT,
            mode_tag    TEXT,
            price       REAL,
            rsi         REAL,
            ema20       REAL,
            stop        REAL,
            target      REAL,
            shares      INTEGER,
            uw_notes    TEXT,
            scan_date   TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            id              INTEGER PRIMARY KEY,
            account_size    REAL DEFAULT 20000,
            weekly_target   REAL DEFAULT 1500,
            swing_risk      REAL DEFAULT 2.0,
            lt_position     REAL DEFAULT 7.5,
            email           TEXT DEFAULT '',
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.execute('''
        INSERT OR IGNORE INTO settings (id, account_size, weekly_target, swing_risk, lt_position)
        VALUES (1, 20000, 1500, 2.0, 7.5)
    ''')
    # Migrate: add scanner columns if they don't exist yet
    for stmt in [
        "ALTER TABLE settings ADD COLUMN scan_rvol_min   REAL DEFAULT 1.5",
        "ALTER TABLE settings ADD COLUMN universe_mode   TEXT DEFAULT 'full'",
        "ALTER TABLE settings ADD COLUMN custom_watchlist TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(stmt)
        except Exception:
            pass  # column already exists
    conn.commit()
    conn.close()


# ─── Settings ─────────────────────────────────────────────────────────────────

def get_settings():
    conn = get_db()
    row = conn.execute('SELECT * FROM settings WHERE id = 1').fetchone()
    conn.close()
    return dict(row) if row else {
        "account_size": 20000, "weekly_target": 1500,
        "swing_risk": 2.0, "lt_position": 7.5, "email": "",
        "scan_rvol_min": 1.5, "universe_mode": "full", "custom_watchlist": "",
    }


def update_settings(data):
    conn = get_db()
    conn.execute('''
        UPDATE settings SET
            account_size     = ?,
            weekly_target    = ?,
            swing_risk       = ?,
            lt_position      = ?,
            email            = ?,
            scan_rvol_min    = ?,
            universe_mode    = ?,
            custom_watchlist = ?,
            updated_at       = ?
        WHERE id = 1
    ''', (
        data.get("account_size", 20000),
        data.get("weekly_target", 1500),
        data.get("swing_risk", 2.0),
        data.get("lt_position", 7.5),
        data.get("email", ""),
        data.get("scan_rvol_min", 1.5),
        data.get("universe_mode", "full"),
        data.get("custom_watchlist", ""),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


# ─── Scan results ─────────────────────────────────────────────────────────────

def save_scan_results(results):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM scan_results WHERE scan_date = ?", (today,))
    for r in results:
        conn.execute('''
            INSERT INTO scan_results
              (ticker, score, verdict, mode_tag, price, rsi, ema20,
               stop, target, shares, uw_notes, scan_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            r.get("ticker"), r.get("score"), r.get("verdict"),
            r.get("mode_tag"), r.get("price"), r.get("rsi"),
            r.get("ema20"), r.get("stop"), r.get("target"),
            r.get("shares"), str(r.get("uw_notes", [])), today
        ))
    conn.commit()
    conn.close()


def get_latest_scan():
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        'SELECT * FROM scan_results WHERE scan_date = ? ORDER BY score DESC',
        (today,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Positions ────────────────────────────────────────────────────────────────

def get_positions():
    conn = get_db()
    rows = conn.execute('SELECT * FROM positions ORDER BY created_at DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_position(data):
    conn = get_db()
    conn.execute('''
        INSERT INTO positions
          (ticker, mode, direction, entry_price, shares, stop, target,
           score, notes, uw_notes, date_open)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        data["ticker"], data.get("mode", "SWING"), data.get("direction", "LONG"),
        data["entry_price"], data["shares"], data.get("stop"), data.get("target"),
        data.get("score", 0), data.get("notes", ""), data.get("uw_notes", ""),
        datetime.now().strftime("%Y-%m-%d")
    ))
    conn.commit()
    conn.close()


def update_position(pos_id, data):
    conn = get_db()
    conn.execute(
        'UPDATE positions SET stop=?, target=?, notes=? WHERE id=?',
        (data.get("stop"), data.get("target"), data.get("notes", ""), pos_id)
    )
    conn.commit()
    conn.close()


def close_position(pos_id):
    conn = get_db()
    pos = conn.execute('SELECT * FROM positions WHERE id=?', (pos_id,)).fetchone()
    result = dict(pos) if pos else {}
    conn.execute('DELETE FROM positions WHERE id=?', (pos_id,))
    conn.commit()
    conn.close()
    return result


# ─── Trades (journal) ─────────────────────────────────────────────────────────

def log_trade(data):
    conn = get_db()
    entry = data.get("entry_price", 0) or 0
    exit_ = data.get("exit_price", 0) or 0
    shares = data.get("shares", 0) or 0
    pnl = round((exit_ - entry) * shares, 2) if entry and exit_ and shares else (data.get("pnl") or 0)
    pnl_pct = round((exit_ - entry) / entry * 100, 2) if entry and exit_ else 0
    conn.execute('''
        INSERT INTO trades
          (ticker, mode, direction, entry_price, exit_price, shares,
           pnl, pnl_pct, stop, target, score, notes, outcome, date_open, date_close)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        data["ticker"], data.get("mode", "SWING"), data.get("direction", "LONG"),
        entry, exit_, shares, pnl, pnl_pct,
        data.get("stop"), data.get("target"), data.get("score", 0),
        data.get("notes", ""),
        "WIN" if pnl > 0 else "LOSS",
        data.get("date_open", datetime.now().strftime("%Y-%m-%d")),
        data.get("date_close", datetime.now().strftime("%Y-%m-%d"))
    ))
    conn.commit()
    conn.close()


def get_trades(limit=100):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM trades ORDER BY created_at DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_db()
    trades = [dict(r) for r in conn.execute('SELECT * FROM trades').fetchall()]
    conn.close()

    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
                "swing_pnl": 0, "lt_pnl": 0, "swing_count": 0, "lt_count": 0}

    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) <= 0]
    swing = [t for t in trades if t.get("mode") == "SWING"]
    lt = [t for t in trades if t.get("mode") == "LONG-TERM"]

    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl": round(sum(t["pnl"] for t in trades), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss": round(gross_loss / len(losses), 2) if losses else 0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else 0,
        "swing_pnl": round(sum(t["pnl"] for t in swing), 2),
        "lt_pnl": round(sum(t["pnl"] for t in lt), 2),
        "swing_count": len(swing),
        "lt_count": len(lt),
    }
