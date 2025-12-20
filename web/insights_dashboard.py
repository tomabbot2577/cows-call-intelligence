#!/usr/bin/env python3
"""
AI Insights Web Dashboard
Secure web interface for viewing call insights with password protection
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.insights_manager_postgresql import get_postgresql_insights_manager
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

# Initialize PostgreSQL insights manager
insights_manager = get_postgresql_insights_manager()


def get_db_connection():
    """Get PostgreSQL database connection"""
    db_config = {
        'dbname': 'call_insights',
        'user': 'call_insights_user',
        'password': 'call_insights_pass',
        'host': 'localhost',
        'port': 5432
    }
    return psycopg2.connect(**db_config)


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
        # Get dashboard statistics
        dashboard_stats = insights_manager.get_dashboard_stats()

        # Get recent recordings
        recent_recordings = insights_manager.get_recent_recordings(limit=10)

        # Get pipeline status
        pipeline_status = insights_manager.get_pipeline_status()

        # Get analytics
        analytics = insights_manager.get_analytics(days=30)

        return render_template('dashboard.html',
                             dashboard_stats=dashboard_stats,
                             recent_recordings=recent_recordings,
                             pipeline_status=pipeline_status,
                             analytics=analytics,
                             datetime=datetime)

    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        flash(f'Error loading dashboard: {e}', 'error')
        return render_template('dashboard.html',
                             dashboard_stats={},
                             recent_recordings=[],
                             pipeline_status={},
                             analytics={},
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
    """Detailed view of specific insight with all 4 AI layers from PostgreSQL"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Fetch all 4 layers from database
        cursor.execute("""
            SELECT
                t.recording_id,
                t.customer_name,
                t.employee_name,
                t.from_number,
                t.to_number,
                t.call_date,
                t.duration_seconds,
                t.transcript_text,
                i.customer_sentiment,
                i.call_quality_score,
                i.call_type,
                i.key_topics,
                i.summary,
                i.follow_up_needed as follow_up_required,
                cr.*,
                rec.process_improvements,
                rec.employee_strengths,
                rec.employee_improvements,
                rec.suggested_phrases,
                rec.follow_up_actions,
                rec.knowledge_base_updates,
                rec.escalation_required as escalation_needed,
                rec.escalation_reason,
                rec.risk_level,
                rec.efficiency_score,
                rec.training_priority
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
            WHERE t.recording_id = %s
        """, (recording_id,))

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if not result:
            flash(f'Recording {recording_id} not found', 'error')
            return redirect(url_for('insights_list'))

        # Structure the data for display with all 4 layers
        insight = dict(result) if result else {}

        # Ensure all fields have default values
        insight.update({
            'recording_id': result['recording_id'],
            # Layer 1: Entity Extraction
            'customer_name': result.get('customer_name') or 'Unknown',
            'employee_name': result.get('employee_name') or 'Unknown',
            'from_phone': result.get('from_number') or 'Unknown',
            'to_phone': result.get('to_number') or 'Unknown',
            'call_date': result.get('call_date'),
            'duration_seconds': result.get('duration_seconds', 0),
            'transcript_text': result.get('transcript_text', ''),
            # Layer 2: Sentiment & Quality Analysis
            'customer_sentiment': result.get('customer_sentiment') or 'Not analyzed',
            'call_quality_score': result.get('call_quality_score', 0),
            'call_type': result.get('call_type') or 'Unknown',
            'key_topics': result.get('key_topics', []),
            'summary': result.get('summary') or 'No summary available',
            'follow_up_required': result.get('follow_up_required') or result.get('follow_up_needed', False),
            # Layer 3: Call Resolution fields (direct from database)
            'resolution_status': result.get('resolution_status'),
            'problem_statement': result.get('problem_statement'),
            'resolution_details': result.get('resolution_details'),
            'solution_summarized': result.get('solution_summarized'),
            'understanding_confirmed': result.get('understanding_confirmed'),
            'asked_if_anything_else': result.get('asked_if_anything_else'),
            'next_steps_provided': result.get('next_steps_provided'),
            'timeline_given': result.get('timeline_given'),
            'contact_info_provided': result.get('contact_info_provided'),
            'closure_score': result.get('closure_score'),
            'missed_best_practices': result.get('missed_best_practices', []),
            'follow_up_type': result.get('follow_up_type'),
            # Layer 4: Recommendations fields (direct from database)
            'process_improvements': result.get('process_improvements', []),
            'employee_strengths': result.get('employee_strengths', []),
            'employee_improvements': result.get('employee_improvements', []),
            'follow_up_actions': result.get('follow_up_actions', []),
            'escalation_needed': result.get('escalation_needed'),
            'escalation_reason': result.get('escalation_reason'),
            'risk_level': result.get('risk_level'),
            'efficiency_score': result.get('efficiency_score')
        })

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
    days = int(request.args.get('days', '30'))

    try:
        report = insights_manager.get_analytics(days=days)
        return render_template('analytics.html',
                             report=report,
                             days=days)

    except Exception as e:
        logger.error(f"Error generating analytics: {e}")
        flash(f'Error generating analytics: {e}', 'error')
        return render_template('analytics.html',
                             report={},
                             days=days)


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
        days = int(request.args.get('days', '30'))
        report = insights_manager.get_analytics(days=days)

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


@app.route('/transcript/<recording_id>')
@require_auth
def view_transcript(recording_id):
    """View original transcript for a recording with all insights"""
    try:
        # Get transcript and all insights from database
        db_config = {
            'dbname': 'call_insights',
            'user': 'call_insights_user',
            'password': 'call_insights_pass',
            'host': 'localhost',
            'port': 5432
        }
        conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # Get complete transcript with all insights joined
        cursor.execute("""
            SELECT
                t.*,
                i.call_quality_score,
                i.customer_sentiment,
                i.call_type,
                i.key_topics,
                i.summary,
                i.follow_up_needed,
                i.escalation_required,
                r.process_improvements,
                r.employee_strengths,
                r.employee_improvements,
                r.suggested_phrases,
                r.follow_up_actions,
                r.knowledge_base_updates,
                r.escalation_required as rec_escalation_required,
                r.risk_level,
                r.escalation_reason,
                r.efficiency_score,
                r.training_priority,
                cr.problem_statement,
                cr.resolution_status,
                cr.resolution_details,
                cr.follow_up_type,
                cr.follow_up_details,
                cr.follow_up_timeline,
                cr.solution_summarized,
                cr.understanding_confirmed,
                cr.asked_if_anything_else,
                cr.next_steps_provided,
                cr.timeline_given,
                cr.contact_info_provided,
                cr.closure_score,
                cr.missed_best_practices,
                cr.improvement_suggestions,
                cr.customer_satisfaction_likely,
                cr.call_back_risk,
                cr.escalation_probability
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_recommendations r ON t.recording_id = r.recording_id
            LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            WHERE t.recording_id = %s
        """, (recording_id,))

        transcript = cursor.fetchone()
        cursor.close()
        conn.close()

        if not transcript:
            flash(f'Transcript not found for recording {recording_id}', 'error')
            return redirect(url_for('insights_list'))

        # Format the transcript for display
        transcript_lines = []
        if transcript.get('transcript_text'):
            # Split into paragraphs for readability
            text = transcript['transcript_text']
            paragraphs = text.split('\n\n') if '\n\n' in text else [text]

            for para in paragraphs:
                if para.strip():
                    transcript_lines.append(para.strip())

        return render_template('transcript_view.html',
                             recording_id=recording_id,
                             transcript=transcript,
                             transcript_lines=transcript_lines)

    except Exception as e:
        logger.error(f"Error loading transcript {recording_id}: {e}")
        flash(f'Error loading transcript: {e}', 'error')
        return redirect(url_for('insights_list'))


@app.route('/api/semantic-search', methods=['POST'])
@require_auth
def semantic_search_api():
    """API endpoint for semantic vector search using Vertex AI RAG"""
    try:
        data = request.get_json()
        query = data.get('query', '')
        filters = data.get('filters', {})
        limit = data.get('limit', 10)

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        # Import Vertex AI search client
        from src.vertex_ai.search_client import VertexSearchClient
        search_client = VertexSearchClient()

        # Perform semantic search via Vertex AI RAG
        results = search_client.semantic_search(
            query=query,
            filters=filters,
            limit=limit
        )

        return jsonify({
            'query': query,
            'results': results,
            'count': len(results)
        })

    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/semantic-search')
@require_auth
def semantic_search_ui():
    """UI page for semantic search"""
    return render_template('semantic_search.html')


@app.route('/api/transcript/<recording_id>')
@require_auth
def get_transcript(recording_id):
    """Get full transcript for a recording"""
    try:
        # Use the insights_manager's db_config
        db_config = {
            'dbname': 'call_insights',
            'user': 'call_insights_user',
            'password': 'call_insights_pass',
            'host': 'localhost',
            'port': 5432
        }
        conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                t.recording_id,
                t.transcript_text,
                t.customer_name,
                t.employee_name,
                t.call_date,
                t.duration_seconds,
                i.summary,
                i.customer_sentiment,
                i.key_topics,
                i.issue_category,
                i.call_type
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            WHERE t.recording_id = %s
        """, (recording_id,))

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return jsonify(dict(result))
        else:
            return jsonify({'error': 'Transcript not found'}), 404

    except Exception as e:
        logger.error(f"Error fetching transcript: {e}")
        return jsonify({'error': str(e)}), 500


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