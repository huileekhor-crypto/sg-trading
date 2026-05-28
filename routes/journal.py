from flask import Blueprint, request, jsonify, session
from models.journal import add_trade, get_trades, delete_trade
from datetime import datetime

journal_bp = Blueprint('journal', __name__)

def _uid():
    return session.get('user_id')

def _enrich(t):
    pnl        = round((t['exit_price'] - t['entry_price']) * t['position_size'], 2)
    return_pct = round((t['exit_price'] - t['entry_price']) / t['entry_price'] * 100, 2)
    return {**t, 'pnl': pnl, 'return_pct': return_pct}

def _stats(trades):
    if not trades:
        return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'avg_win_pct': 0, 'avg_loss_pct': 0, 'total_pnl': 0}
    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    return {
        'total':        len(trades),
        'wins':         len(wins),
        'losses':       len(losses),
        'win_rate':     round(len(wins) / len(trades) * 100, 1),
        'avg_win_pct':  round(sum(t['return_pct'] for t in wins)   / len(wins),   2) if wins   else 0,
        'avg_loss_pct': round(sum(t['return_pct'] for t in losses) / len(losses), 2) if losses else 0,
        'total_pnl':    round(sum(t['pnl'] for t in trades), 2),
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
    return jsonify({'trades': trades, 'stats': _stats(trades)})

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
        exit_   = float(d['exit_price'])
        size    = float(d['position_size'])
        emotion = int(d.get('emotion', 3))
        if entry <= 0 or exit_ <= 0 or size <= 0:
            raise ValueError('Prices and size must be positive')
        if not 1 <= emotion <= 5:
            raise ValueError('Emotion must be 1-5')
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': str(e) or 'Invalid trade values'}), 400
    trade_date = d.get('trade_date') or datetime.now().strftime('%Y-%m-%d')
    setup_type = d.get('setup_type', 'Other')
    notes      = d.get('notes', '').strip()
    add_trade(uid, ticker, trade_date, entry, exit_, size, setup_type, emotion, notes)
    return jsonify({'success': True})

@journal_bp.route('/journal/<int:trade_id>', methods=['DELETE'])
def delete_journal(trade_id):
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    delete_trade(uid, trade_id)
    return jsonify({'success': True})
