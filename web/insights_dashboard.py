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
from src.insights.customer_employee_identifier import get_customer_employee_identifier

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
                             patterns=patterns,
                             datetime=datetime)

    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        flash(f'Error loading dashboard: {e}', 'error')
        return render_template('dashboard.html',
                             recent_insights=[],
                             analytics={},
                             patterns=[],
                             datetime=datetime)


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


@app.route('/customer-search')
@require_auth
def customer_search():
    """Customer search interface"""
    search_params = {
        'search_term': request.args.get('search_term', '').strip(),
        'search_type': request.args.get('search_type', 'any'),
        'date_range': request.args.get('date_range', 'all'),
    }

    search_performed = bool(search_params['search_term'])
    search_results = []
    unique_customers = 0
    escalations_count = 0
    avg_satisfaction = 0

    if search_performed:
        try:
            # Initialize customer identifier for searching
            identifier = get_customer_employee_identifier()

            # Load all transcription files for searching
            transcription_files = []
            transcriptions_dir = Path('/var/www/call-recording-system/data/transcriptions/json')

            for json_file in transcriptions_dir.rglob('*.json'):
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                        transcription_files.append(data)
                except Exception as e:
                    logger.error(f"Error loading {json_file}: {e}")
                    continue

            # Search through transcriptions
            matching_calls = identifier.search_calls_by_customer(
                search_params['search_term'], transcription_files
            )

            # Process results for display
            for call in matching_calls:
                participants = call.get('participants', {})
                employee = participants.get('primary_employee', {})
                customer = participants.get('primary_customer', {})
                metadata = participants.get('call_metadata', {})

                search_results.append({
                    'recording_id': call.get('recording_id'),
                    'call_date': metadata.get('date'),
                    'duration_seconds': metadata.get('duration'),
                    'customer_name': customer.get('name'),
                    'customer_company': customer.get('company'),
                    'customer_phone': customer.get('phone'),
                    'customer_email': customer.get('email'),
                    'employee_name': employee.get('name'),
                    'employee_extension': employee.get('extension'),
                    'employee_department': employee.get('department'),
                    'call_type': 'support',  # Default for now
                    'urgency_level': 'medium',  # Default
                    'customer_satisfaction_score': 7,  # Default
                    'escalation_required': False,
                    'follow_up_needed': False,
                    'technical_issue': 'technical' in participants.get('call_context', {}).get('mentioned_issues', []),
                    'billing_issue': 'billing' in participants.get('call_context', {}).get('mentioned_products', []),
                    'sales_opportunity': False
                })

            # Calculate summary stats
            unique_customers = len(set(r['customer_name'] for r in search_results if r['customer_name']))
            escalations_count = sum(1 for r in search_results if r['escalation_required'])
            satisfaction_scores = [r['customer_satisfaction_score'] for r in search_results if r['customer_satisfaction_score']]
            avg_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores) if satisfaction_scores else 0

        except Exception as e:
            logger.error(f"Customer search error: {e}")
            flash(f'Search error: {e}', 'error')

    return render_template('customer_search.html',
                          search_params=search_params,
                          search_performed=search_performed,
                          search_results=search_results,
                          unique_customers=unique_customers,
                          escalations_count=escalations_count,
                          avg_satisfaction=avg_satisfaction)


@app.route('/customer-analytics/<customer_id>')
@require_auth
def customer_analytics(customer_id):
    """Customer analytics page"""
    try:
        # Initialize customer identifier
        identifier = get_customer_employee_identifier()

        # Load all transcription files
        transcription_files = []
        transcriptions_dir = Path('/var/www/call-recording-system/data/transcriptions/json')

        for json_file in transcriptions_dir.rglob('*.json'):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    transcription_files.append(data)
            except Exception as e:
                continue

        # Get customer call history
        matching_calls = identifier.search_calls_by_customer(customer_id, transcription_files)

        if not matching_calls:
            customer_data = {"error": f"No calls found for customer: {customer_id}"}
        else:
            # Process calls for analytics
            processed_calls = []
            for call in matching_calls:
                participants = call.get('participants', {})
                employee = participants.get('primary_employee', {})
                customer = participants.get('primary_customer', {})
                metadata = participants.get('call_metadata', {})

                processed_calls.append({
                    'recording_id': call.get('recording_id'),
                    'call_date': metadata.get('date'),
                    'duration_seconds': metadata.get('duration'),
                    'customer_satisfaction_score': 7,  # Default
                    'escalation_required': False,
                    'follow_up_needed': False,
                    'technical_issue': False,
                    'billing_issue': False,
                    'sales_opportunity': False,
                    'call_type': 'support',
                    'employee_name': employee.get('name'),
                    'employee_department': employee.get('department')
                })

            # Generate analytics
            total_calls = len(processed_calls)
            satisfaction_scores = [c['customer_satisfaction_score'] for c in processed_calls if c['customer_satisfaction_score']]
            avg_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores) if satisfaction_scores else 0

            # Call types breakdown
            call_types = {}
            departments = {}
            employees = {}

            for call in processed_calls:
                call_type = call['call_type']
                call_types[call_type] = call_types.get(call_type, 0) + 1

                dept = call['employee_department'] or 'unknown'
                departments[dept] = departments.get(dept, 0) + 1

                emp = call['employee_name'] or 'unknown'
                employees[emp] = employees.get(emp, 0) + 1

            escalations = sum(1 for c in processed_calls if c['escalation_required'])
            follow_ups = sum(1 for c in processed_calls if c['follow_up_needed'])
            technical_issues = sum(1 for c in processed_calls if c['technical_issue'])
            billing_issues = sum(1 for c in processed_calls if c['billing_issue'])

            customer_data = {
                "customer_identifier": customer_id,
                "summary": {
                    "total_calls": total_calls,
                    "average_satisfaction": round(avg_satisfaction, 2),
                    "first_call_date": processed_calls[-1]['call_date'] if processed_calls else None,
                    "last_call_date": processed_calls[0]['call_date'] if processed_calls else None,
                    "total_escalations": escalations,
                    "total_follow_ups": follow_ups
                },
                "breakdown": {
                    "call_types": call_types,
                    "departments_contacted": departments,
                    "employees_spoken_with": employees
                },
                "issues": {
                    "technical_issues": technical_issues,
                    "billing_issues": billing_issues,
                    "escalation_rate": round(escalations / total_calls * 100, 1) if total_calls > 0 else 0
                },
                "recent_calls": processed_calls[:10],
                "trend_analysis": {
                    "satisfaction_trend": "stable",
                    "call_frequency_trend": "stable",
                    "issue_complexity_trend": "stable",
                    "relationship_health": "good"
                }
            }

    except Exception as e:
        logger.error(f"Customer analytics error: {e}")
        customer_data = {"error": f"Error generating analytics: {e}"}

    return render_template('customer_analytics.html', customer_data=customer_data)


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