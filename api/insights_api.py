#!/usr/bin/env python3
"""
AI Insights API - RESTful endpoints for accessing call insights
Designed for N8N, webhooks, and third-party integrations
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
import logging

sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.insights_manager import get_insights_manager

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize insights manager
insights_manager = get_insights_manager()


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'insights_api'
    })


@app.route('/insights', methods=['GET'])
def list_insights():
    """
    List insights with flexible filtering

    Query Parameters:
    - start_date: Filter by start date (YYYY-MM-DD)
    - end_date: Filter by end date (YYYY-MM-DD)
    - agent_id: Filter by agent ID
    - customer_id: Filter by customer ID
    - min_quality_score: Minimum quality score (0-10)
    - sentiment: Customer sentiment (positive/neutral/negative)
    - category: Issue category
    - limit: Maximum results (default: 100)
    """
    try:
        params = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'agent_id': request.args.get('agent_id'),
            'customer_id': request.args.get('customer_id'),
            'min_quality_score': request.args.get('min_quality_score', type=float),
            'sentiment': request.args.get('sentiment'),
            'category': request.args.get('category'),
            'limit': request.args.get('limit', 100, type=int)
        }

        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}

        insights = insights_manager.query_insights(**params)

        return jsonify({
            'status': 'success',
            'count': len(insights),
            'data': insights
        })

    except Exception as e:
        logger.error(f"Error listing insights: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/insights/<recording_id>', methods=['GET'])
def get_insight(recording_id):
    """Get detailed insight for specific recording"""
    try:
        # Try to load raw insight
        raw_path = Path(f'/var/www/call-recording-system/data/transcriptions/insights/{recording_id}_insights.json')

        if not raw_path.exists():
            return jsonify({
                'status': 'error',
                'message': f'Insight not found for recording {recording_id}'
            }), 404

        with open(raw_path, 'r') as f:
            insight = json.load(f)

        return jsonify({
            'status': 'success',
            'data': insight
        })

    except Exception as e:
        logger.error(f"Error getting insight: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/insights', methods=['POST'])
def store_insight():
    """
    Store new insight (typically from batch processor)

    Request Body:
    - recording_id: Recording identifier
    - insight_data: Complete insight data
    """
    try:
        data = request.json
        recording_id = data.get('recording_id')
        insight_data = data.get('insight_data')

        if not recording_id or not insight_data:
            return jsonify({
                'status': 'error',
                'message': 'recording_id and insight_data required'
            }), 400

        success = insights_manager.store_insight(recording_id, insight_data)

        if success:
            return jsonify({
                'status': 'success',
                'message': f'Insight stored for {recording_id}'
            }), 201
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to store insight'
            }), 500

    except Exception as e:
        logger.error(f"Error storing insight: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/analytics/summary', methods=['GET'])
def analytics_summary():
    """
    Get analytics summary

    Query Parameters:
    - period: daily, weekly, or monthly (default: daily)
    """
    try:
        period = request.args.get('period', 'daily')

        if period not in ['daily', 'weekly', 'monthly']:
            return jsonify({
                'status': 'error',
                'message': 'Period must be daily, weekly, or monthly'
            }), 400

        report = insights_manager.generate_analytics_report(period)

        return jsonify({
            'status': 'success',
            'data': report
        })

    except Exception as e:
        logger.error(f"Error generating analytics: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/analytics/agent/<agent_id>', methods=['GET'])
def agent_analytics(agent_id):
    """Get analytics for specific agent"""
    try:
        limit = request.args.get('limit', 50, type=int)

        insights = insights_manager.query_insights(
            agent_id=agent_id,
            limit=limit
        )

        # Calculate agent metrics
        if insights:
            total_calls = len(insights)
            avg_quality = sum(i.get('call_quality_score', 0) for i in insights) / total_calls
            avg_satisfaction = sum(i.get('customer_satisfaction_score', 0) for i in insights) / total_calls
            escalations = sum(1 for i in insights if i.get('escalation_required'))

            metrics = {
                'total_calls': total_calls,
                'avg_quality_score': round(avg_quality, 2),
                'avg_satisfaction_score': round(avg_satisfaction, 2),
                'escalation_rate': round(escalations / total_calls * 100, 2),
                'recent_calls': insights[:10]
            }
        else:
            metrics = {
                'total_calls': 0,
                'avg_quality_score': 0,
                'avg_satisfaction_score': 0,
                'escalation_rate': 0,
                'recent_calls': []
            }

        return jsonify({
            'status': 'success',
            'agent_id': agent_id,
            'metrics': metrics
        })

    except Exception as e:
        logger.error(f"Error getting agent analytics: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/patterns', methods=['GET'])
def get_patterns():
    """Get detected patterns and trends"""
    try:
        patterns = insights_manager._get_patterns()

        return jsonify({
            'status': 'success',
            'count': len(patterns),
            'patterns': patterns
        })

    except Exception as e:
        logger.error(f"Error getting patterns: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/quick-wins', methods=['GET'])
def get_quick_wins():
    """Get all quick wins identified"""
    try:
        # Query quick wins from database
        import sqlite3
        conn = sqlite3.connect(insights_manager.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM quick_wins
            WHERE status = 'pending'
            ORDER BY priority, impact_score DESC
            LIMIT 50
        ''')

        quick_wins = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify({
            'status': 'success',
            'count': len(quick_wins),
            'quick_wins': quick_wins
        })

    except Exception as e:
        logger.error(f"Error getting quick wins: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/training-needs', methods=['GET'])
def get_training_needs():
    """Get identified training needs"""
    try:
        import sqlite3
        conn = sqlite3.connect(insights_manager.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM training_needs
            ORDER BY deadline, (target_level - current_level) DESC
        ''')

        training_needs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify({
            'status': 'success',
            'count': len(training_needs),
            'training_needs': training_needs
        })

    except Exception as e:
        logger.error(f"Error getting training needs: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/export', methods=['GET'])
def export_insights():
    """
    Export insights for external processing

    Query Parameters:
    - format: jsonl (for LLM training) or context (for RAG)
    """
    try:
        export_format = request.args.get('format', 'context')

        if export_format not in ['jsonl', 'context']:
            return jsonify({
                'status': 'error',
                'message': 'Format must be jsonl or context'
            }), 400

        export_path = insights_manager.export_for_llm(export_format)

        return send_file(
            export_path,
            as_attachment=True,
            download_name=export_path.name
        )

    except Exception as e:
        logger.error(f"Error exporting insights: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/webhooks/new-insight', methods=['POST'])
def webhook_new_insight():
    """
    Webhook endpoint for N8N to receive new insight notifications

    This would typically trigger workflows in N8N
    """
    try:
        data = request.json
        recording_id = data.get('recording_id')

        # Here you would typically:
        # 1. Validate the webhook
        # 2. Process the insight
        # 3. Trigger any necessary workflows

        logger.info(f"Webhook received for recording {recording_id}")

        return jsonify({
            'status': 'success',
            'message': 'Webhook processed'
        }), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/search', methods=['POST'])
def search_insights():
    """
    Advanced search with multiple criteria

    Request Body:
    - query: Text search query
    - filters: Object with filter criteria
    """
    try:
        data = request.json
        query = data.get('query', '')
        filters = data.get('filters', {})

        # This would implement full-text search
        # For now, use basic filtering
        insights = insights_manager.query_insights(**filters)

        # Filter by query if provided
        if query:
            query_lower = query.lower()
            insights = [
                i for i in insights
                if query_lower in str(i.get('summary', '')).lower()
                or query_lower in str(i.get('key_topics', [])).lower()
            ]

        return jsonify({
            'status': 'success',
            'count': len(insights),
            'data': insights
        })

    except Exception as e:
        logger.error(f"Error searching insights: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    # Run the API server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False
    )