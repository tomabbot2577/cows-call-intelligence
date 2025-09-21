#!/usr/bin/env python3
"""
AI Insights Web Dashboard
Secure web interface for viewing call insights with password protection
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
import logging

sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.insights_manager import get_insights_manager

app = Flask(__name__)

# Configure session
app.config['SECRET_KEY'] = 'pcr-insights-secret-key-2025'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/var/www/call-recording-system/web/sessions'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
Session(app)

# Create sessions directory
Path(app.config['SESSION_FILE_DIR']).mkdir(parents=True, exist_ok=True)

# Password hash for !pcr123
PASSWORD_HASH = generate_password_hash('!pcr123')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize insights manager
insights_manager = get_insights_manager()


def require_auth(f):
    """Decorator to require authentication"""
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page with password protection"""
    if request.method == 'POST':
        password = request.form.get('password')

        if password and check_password_hash(PASSWORD_HASH, password):
            session['authenticated'] = True
            session.permanent = True
            logger.info(f"Successful login from {request.remote_addr}")
            return redirect(url_for('dashboard'))
        else:
            logger.warning(f"Failed login attempt from {request.remote_addr}")
            flash('Invalid password', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@require_auth
def dashboard():
    """Main dashboard page"""
    try:
        # Get recent insights
        recent_insights = insights_manager.query_insights(limit=10)

        # Get analytics summary
        analytics = insights_manager.generate_analytics_report('daily')

        # Get patterns
        patterns = insights_manager._get_patterns()[:5]

        return render_template('dashboard.html',
                             recent_insights=recent_insights,
                             analytics=analytics,
                             patterns=patterns)

    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        flash(f'Error loading dashboard: {e}', 'error')
        return render_template('dashboard.html',
                             recent_insights=[],
                             analytics={},
                             patterns=[])


@app.route('/insights')
@require_auth
def insights_list():
    """List all insights with filtering"""
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    agent_id = request.args.get('agent_id')
    sentiment = request.args.get('sentiment')
    category = request.args.get('category')
    limit = int(request.args.get('limit', 50))

    # Build filter dict
    filters = {}
    if start_date:
        filters['start_date'] = start_date
    if end_date:
        filters['end_date'] = end_date
    if agent_id:
        filters['agent_id'] = agent_id
    if sentiment:
        filters['sentiment'] = sentiment
    if category:
        filters['category'] = category

    # Query insights
    insights = insights_manager.query_insights(limit=limit, **filters)

    return render_template('insights_list.html',
                          insights=insights,
                          filters=filters)


@app.route('/insight/<recording_id>')
@require_auth
def insight_detail(recording_id):
    """Detailed view of specific insight"""
    try:
        # Load raw insight
        raw_path = Path(f'/var/www/call-recording-system/data/transcriptions/insights/{recording_id}_insights.json')

        if not raw_path.exists():
            flash(f'Insight not found for recording {recording_id}', 'error')
            return redirect(url_for('insights_list'))

        with open(raw_path, 'r') as f:
            insight = json.load(f)

        return render_template('insight_detail.html',
                             insight=insight,
                             recording_id=recording_id)

    except Exception as e:
        logger.error(f"Error loading insight {recording_id}: {e}")
        flash(f'Error loading insight: {e}', 'error')
        return redirect(url_for('insights_list'))


@app.route('/analytics')
@require_auth
def analytics():
    """Analytics and reporting page"""
    period = request.args.get('period', 'weekly')

    try:
        report = insights_manager.generate_analytics_report(period)
        return render_template('analytics.html',
                             report=report,
                             period=period)

    except Exception as e:
        logger.error(f"Error generating analytics: {e}")
        flash(f'Error generating analytics: {e}', 'error')
        return render_template('analytics.html',
                             report={},
                             period=period)


@app.route('/api/insights')
@require_auth
def api_insights():
    """JSON API endpoint for insights"""
    try:
        filters = {k: v for k, v in request.args.items() if v}
        limit = int(filters.pop('limit', 100))

        insights = insights_manager.query_insights(limit=limit, **filters)

        return jsonify({
            'status': 'success',
            'count': len(insights),
            'data': insights
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/analytics')
@require_auth
def api_analytics():
    """JSON API endpoint for analytics"""
    try:
        period = request.args.get('period', 'daily')
        report = insights_manager.generate_analytics_report(period)

        return jsonify({
            'status': 'success',
            'data': report
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    templates_dir = Path('/var/www/call-recording-system/web/templates')
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Run the dashboard
    app.run(
        host='0.0.0.0',
        port=5001,
        debug=False
    )