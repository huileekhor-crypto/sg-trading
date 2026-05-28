from flask import Blueprint, request, jsonify, session
from models.alerts import add_alert, get_alerts, delete_alert, ack_alerts, unseen_count

alerts_bp = Blueprint('alerts', __name__)

def _uid():
    return session.get('user_id')

@alerts_bp.route('/alerts', methods=['GET'])
def get_user_alerts():
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    return jsonify({'alerts': get_alerts(uid)})

@alerts_bp.route('/alerts/add', methods=['POST'])
def add_user_alert():
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    d         = request.get_json() or {}
    ticker    = d.get('ticker', '').strip().upper()
    condition = d.get('condition', '').lower()
    if not ticker:
        return jsonify({'error': 'Ticker is required'}), 400
    if condition not in ('above', 'below'):
        return jsonify({'error': 'Condition must be above or below'}), 400
    try:
        target = float(d['target'])
        if target <= 0:
            raise ValueError('Target price must be positive')
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': str(e) or 'Invalid target price'}), 400
    add_alert(uid, ticker, target, condition)
    return jsonify({'success': True})

@alerts_bp.route('/alerts/<int:alert_id>', methods=['DELETE'])
def delete_user_alert(alert_id):
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    delete_alert(uid, alert_id)
    return jsonify({'success': True})

@alerts_bp.route('/alerts/ack', methods=['POST'])
def ack_user_alerts():
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401
    ack_alerts(uid)
    return jsonify({'success': True})

@alerts_bp.route('/alerts/badge', methods=['GET'])
def alert_badge():
    uid = _uid()
    if not uid:
        return jsonify({'count': 0})
    return jsonify({'count': unseen_count(uid)})
