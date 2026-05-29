from flask import Blueprint, request, jsonify, session
from models.journal import add_trade, get_trades, delete_trade, update_trade
from datetime import datetime

journal_bp = Blueprint('journal', __name__)

def _uid():
    return session.get('user_id')

def _enrich(t):
    is_open = t['exit_price'] == 0
    if is_open:
        return {**t, 'is_open': True, 'pnl': None, 'return_pct': None}
    pnl        = round((t['exit_price'] - t['entry_price']) * t['position_size'], 2)
    return_pct = round((t['exit_price'] - t['entry_price']) / t['entry_price'] * 100, 2)
    return {**t, 'is_open': False, 'pnl': pnl, 'return_pct': return_pct}

def _stats(trades):
    closed = [t for t in trades if not t.get('is_open')]
    if not closed:
        return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'avg_win_pct': 0, 'avg_loss_pct': 0, 'total_pnl': 0,
                'open_count': len([t for t in trades if t.get('is_open')])}
    wins   = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    return {
        'total':        len(closed),
        'wins':         len(wins),
        'losses':       len(losses),
        'win_rate':     round(len(wins) / len(closed) * 100, 1),
        'avg_win_pct':  round(sum(t['return_pct'] for t in wins)   / len(wins),   2) if wins   else 0,
        'avg_loss_pct': round(sum(t['return_pct'] for t in losses) / len(losses), 2) if losses else 0,
        'total_pnl':    round(sum(t['pnl'] for t in closed), 2),
        'open_count':   len([t for t in trades if t.get('is_open')]),
        'best_trade':   max((t['return_pct'] for t in wins),   default=0),
        'worst_trade':  min((t['return_pct'] for t in losses), default=0),
    }

@journal_bp.route('/journal', methods=['GET'])
def get_journal():
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    ticker    = request.args.get('ticker', '').strip() or None
    date_from = request.args.get('from',   '').strip() or None
    date_to   = request.args.get('to',     '').strip() or None
    trades = [_enrich(t) for t in get_trades(uid, ticker, date_from, date_to)]
    open_trades   = [t for t in trades if t.get('is_open')]
    closed_trades = [t for t in trades if not t.get('is_open')]
    return jsonify({'trades': trades, 'open': open_trades,
                    'closed': closed_trades, 'stats': _stats(trades)})

@journal_bp.route('/journal/add', methods=['POST'])
def add_journal():
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    d      = request.get_json() or {}
    ticker = d.get('ticker', '').strip().upper()
    if not ticker:
        return jsonify({'error': 'Ticker is required'}), 400
    try:
        entry   = float(d['entry_price'])
        exit_   = float(d.get('exit_price', 0))   # 0 = open position
        size    = float(d['position_size'])
        emotion = int(d.get('emotion', 3))
        if entry <= 0 or exit_ < 0 or size <= 0:
            raise ValueError('Entry and size must be positive; exit 0 = open trade')
        if not 1 <= emotion <= 5:
            raise ValueError('Emotion must be 1-5')
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': str(e) or 'Invalid trade values'}), 400
    trade_date = d.get('trade_date') or datetime.now().strftime('%Y-%m-%d')
    setup_type = d.get('setup_type', 'Other')
    notes      = d.get('notes', '').strip()
    add_trade(uid, ticker, trade_date, entry, exit_, size, setup_type, emotion, notes)
    return jsonify({'success': True})

@journal_bp.route('/journal/<int:trade_id>/close', methods=['PATCH'])
def close_journal(trade_id):
    """Close an open position by setting the exit price."""
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    d = request.get_json() or {}
    try:
        exit_price = float(d['exit_price'])
        if exit_price <= 0:
            raise ValueError('Exit price must be positive')
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': str(e)}), 400
    update_trade(uid, trade_id, exit_price)
    return jsonify({'success': True})

@journal_bp.route('/journal/<int:trade_id>', methods=['DELETE'])
def delete_journal(trade_id):
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    delete_trade(uid, trade_id)
    return jsonify({'success': True})
