from flask import Blueprint, request, jsonify, session
from models.alerts import (add_alert, get_alerts, delete_alert, ack_alerts, unseen_count,
                            get_recipients, add_recipient, delete_recipient, toggle_recipient,
                            get_active_recipients)

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


# ── Email recipient management ────────────────────────────────────────────────

@alerts_bp.route('/alerts/recipients', methods=['GET'])
def list_recipients():
    if not _uid():
        return jsonify({'error': 'Not authenticated'}), 401
    from config import Config
    return jsonify({
        'recipients':    get_recipients(),
        'email_configured': bool(Config.EMAIL_SENDER and Config.EMAIL_PASSWORD),
    })


@alerts_bp.route('/alerts/recipients/add', methods=['POST'])
def add_email_recipient():
    if not _uid():
        return jsonify({'error': 'Not authenticated'}), 401
    d     = request.get_json() or {}
    email = d.get('email', '').strip().lower()
    name  = d.get('name', '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email address required'}), 400
    add_recipient(email, name)
    return jsonify({'success': True, 'recipients': get_recipients()})


@alerts_bp.route('/alerts/recipients/<int:rid>', methods=['DELETE'])
def remove_recipient(rid):
    if not _uid():
        return jsonify({'error': 'Not authenticated'}), 401
    delete_recipient(rid)
    return jsonify({'success': True, 'recipients': get_recipients()})


@alerts_bp.route('/alerts/recipients/<int:rid>', methods=['PUT'])
def toggle_recipient_active(rid):
    if not _uid():
        return jsonify({'error': 'Not authenticated'}), 401
    toggle_recipient(rid)
    return jsonify({'success': True, 'recipients': get_recipients()})


@alerts_bp.route('/alerts/test-email', methods=['POST'])
def test_email():
    if not _uid():
        return jsonify({'error': 'Not authenticated'}), 401
    from utils.emailer import send_test_email
    from config import Config
    if not Config.EMAIL_SENDER or not Config.EMAIL_PASSWORD:
        return jsonify({'error': 'Email not configured — set EMAIL_SENDER and EMAIL_PASSWORD in Azure Application Settings'}), 400

    recipients = get_active_recipients()
    if not recipients:
        return jsonify({'error': 'No active recipients — add at least one email address first'}), 400

    ok, errors = 0, []
    for r in recipients:
        success, err = send_test_email(r['email'], r.get('name') or None)
        if success:
            ok += 1
        else:
            errors.append(f"{r['email']}: {err}")

    if ok:
        return jsonify({'success': True, 'sent': ok, 'errors': errors})
    return jsonify({'error': '; '.join(errors)}), 500
