"""RAG Integration FastAPI Application"""

import os
import sys
import smtplib
import ssl
from datetime import datetime
from typing import Optional, List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from pathlib import Path

# Add project to path
sys.path.insert(0, '/var/www/call-recording-system')

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from psycopg2.extras import RealDictCursor
import uvicorn

from rag_integration.config.settings import get_config
from rag_integration.config.employee_names import get_canonical_employee_list, CANONICAL_EMPLOYEES, get_employee_name_variations
from rag_integration.services.db_reader import DatabaseReader
from rag_integration.services.gemini_file_search import GeminiFileSearchService
from rag_integration.services.vertex_rag import VertexRAGService
from rag_integration.services.query_router import UnifiedQueryService, QueryRouter
from rag_integration.services.dashboard_metrics import DashboardMetricsService, get_metrics_service
from rag_integration.jobs.export_pipeline import ExportPipeline

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="ConvoMetrics BLT API",
    description="Hybrid RAG system for call intelligence",
    version="1.0.0"
)

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key="cows-rag-secret-key-change-in-prod")

# Setup templates
template_dir = Path(__file__).parent / "templates"
template_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(template_dir))

# Setup static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Global services (lazy initialized)
_config = None
_query_service = None
_pipeline = None
_db_reader = None


def get_config_instance():
    global _config
    if _config is None:
        _config = get_config()
    return _config


def get_query_service():
    global _query_service
    if _query_service is None:
        config = get_config_instance()
        gemini = GeminiFileSearchService(config.gemini_api_key)
        vertex = VertexRAGService(config.gcp_project, config.vertex_location)
        _query_service = UnifiedQueryService(gemini, vertex)
    return _query_service


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = ExportPipeline()
    return _pipeline


def get_db():
    global _db_reader
    if _db_reader is None:
        _db_reader = DatabaseReader()
    return _db_reader


# Authentication
def get_auth_service():
    """Get AuthService instance."""
    from rag_integration.services.auth import AuthService
    return AuthService()


def check_auth(request: Request) -> bool:
    """Check if user is authenticated."""
    return request.session.get("authenticated", False)


def get_current_user(request: Request) -> Optional[Dict]:
    """Get current user from session."""
    if not check_auth(request):
        return None
    return request.session.get("user")


def require_auth(request: Request):
    """Require authentication dependency."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return True


def is_admin(request: Request) -> bool:
    """Check if current user is admin."""
    user = get_current_user(request)
    return user and user.get('role') == 'admin'


def get_employee_filter(request: Request) -> Optional[str]:
    """Get employee name filter for non-admin users."""
    user = get_current_user(request)
    if not user:
        return None
    if user.get('role') == 'admin':
        return None  # Admin sees all
    return user.get('employee_name')


# Pydantic models
class QueryRequest(BaseModel):
    query: str
    force_system: Optional[str] = None


class QueryResponse(BaseModel):
    query: str
    system: str
    response: str
    citations: List[Dict] = []
    filters: Optional[Dict] = None
    query_time_ms: int


class ExportRequest(BaseModel):
    since_date: Optional[str] = None
    batch_size: int = 100
    skip_gcs: bool = False
    skip_gemini: bool = False
    skip_vertex: bool = False


class EmailReportRequest(BaseModel):
    recipient_email: str
    report_title: str
    report_content: str
    report_type: Optional[str] = "general"


# Email configuration from environment
def get_email_config():
    """Get email configuration from environment."""
    from dotenv import load_dotenv
    load_dotenv('/var/www/call-recording-system/.env')

    return {
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_password": os.getenv("GMAIL_APP_PASSWORD", os.getenv("SMTP_PASSWORD", "")).replace(" ", ""),
        "from_name": "ConvoMetrics BLT"
    }


def send_email(to_email: str, subject: str, body: str) -> Dict[str, Any]:
    """Send email via SMTP with improved deliverability."""
    import uuid
    from email.utils import formatdate, make_msgid

    config = get_email_config()

    if not config["smtp_user"] or not config["smtp_password"]:
        raise ValueError("SMTP credentials not configured")

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"Main Sequence Technology <{config['smtp_user']}>"
    msg['To'] = to_email
    msg['Reply-To'] = config['smtp_user']
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='mainsequence.net')

    # Add headers to improve deliverability
    msg['X-Priority'] = '3'  # Normal priority
    msg['X-Mailer'] = 'Main Sequence Report System'

    # Plain text version first (important for spam filters)
    plain_body = f"""
{body}

---
This report was shared with you by a colleague at Main Sequence Technology.
Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
    """

    # Clean HTML version
    html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px;">
    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #3498db;">
        <pre style="white-space: pre-wrap; word-wrap: break-word; font-family: inherit; margin: 0;">{body}</pre>
    </div>
    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #666; font-size: 12px;">
        <p>This report was shared with you by a colleague at Main Sequence Technology.</p>
        <p>Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
    </div>
</body>
</html>"""

    # Attach plain text first, then HTML (order matters for spam filters)
    msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    context = ssl.create_default_context()

    with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
        server.starttls(context=context)
        server.login(config["smtp_user"], config["smtp_password"])
        server.send_message(msg)

    return {"success": True, "recipient": to_email}


# Health check
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }


# Authentication routes
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Process login with username and password."""
    auth = get_auth_service()
    user = auth.authenticate(username, password)

    if user:
        request.session["authenticated"] = True
        request.session["user"] = user

        # Check if password change required
        if user.get('must_change_password'):
            return RedirectResponse(url="/change-password", status_code=303)

        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid username or password"
    })


@app.get("/logout")
async def logout(request: Request):
    """Logout."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    """Password change page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(request)
    forced = user.get('must_change_password', False) if user else False

    return templates.TemplateResponse("change_password.html", {
        "request": request,
        "user": user,
        "forced": forced,
        "error": None,
        "success": None
    })


@app.post("/change-password")
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Process password change."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Validate passwords match
    if new_password != confirm_password:
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "forced": user.get('must_change_password', False),
            "error": "New passwords do not match",
            "success": None
        })

    auth = get_auth_service()
    result = auth.change_password(user['username'], current_password, new_password)

    if result['success']:
        # Update session to remove must_change_password flag
        user['must_change_password'] = False
        request.session["user"] = user
        return RedirectResponse(url="/?password_changed=1", status_code=303)
    else:
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "forced": user.get('must_change_password', False),
            "error": result.get('error', 'Failed to change password'),
            "success": None
        })


# Web UI routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        db = get_db()
        stats = db.get_statistics()
        pipeline = get_pipeline()
        pipeline_status = pipeline.get_status()

        return templates.TemplateResponse("index.html", {
            "request": request,
            "stats": stats,
            "pipeline": pipeline_status
        })
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "stats": {},
            "pipeline": {},
            "error": str(e)
        })


@app.get("/query", response_class=HTMLResponse)
async def query_page(request: Request):
    """Query interface page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse("query.html", {
        "request": request,
        "result": None,
        "selected_date_range": None,
        "start_date": None,
        "end_date": None
    })


@app.post("/query", response_class=HTMLResponse)
async def query_submit(
    request: Request,
    query: str = Form(...),
    system: str = Form("auto"),
    date_range: str = Form(None),
    start_date: str = Form(None),
    end_date: str = Form(None)
):
    """Process query from web form."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        service = get_query_service()
        force_system = None if system == "auto" else system

        # Add date range context to query if specified
        query_with_context = query
        if date_range and date_range != 'custom':
            date_labels = {
                'last_30': 'last 30 days',
                'mtd': 'month to date',
                'qtd': 'quarter to date',
                'ytd': 'year to date'
            }
            if date_range in date_labels:
                query_with_context = f"{query} (limit to {date_labels[date_range]})"
        elif date_range == 'custom' and start_date and end_date:
            query_with_context = f"{query} (limit to date range {start_date} to {end_date})"

        result = service.query(query_with_context, force_system=force_system)

        # Add date range info to result
        if date_range:
            result['date_range'] = date_range
            if date_range == 'custom':
                result['date_range'] = f"{start_date} to {end_date}"

        return templates.TemplateResponse("query.html", {
            "request": request,
            "result": result,
            "query": query,
            "selected_system": system,
            "selected_date_range": date_range,
            "start_date": start_date,
            "end_date": end_date
        })
    except Exception as e:
        logger.error(f"Query error: {e}")
        return templates.TemplateResponse("query.html", {
            "request": request,
            "result": None,
            "error": str(e),
            "query": query,
            "selected_system": system,
            "selected_date_range": date_range,
            "start_date": start_date,
            "end_date": end_date
        })


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Reports page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # Get list of canonical employee names
    from rag_integration.config.employee_names import get_canonical_employee_list
    agents = get_canonical_employee_list()

    # Get list of customer companies
    try:
        db = get_db()
        customers = db.get_customer_companies(limit=100)
    except Exception:
        customers = []

    return templates.TemplateResponse("reports.html", {
        "request": request,
        "agents": agents,
        "customers": customers
    })


@app.get("/export", response_class=HTMLResponse)
async def export_page(request: Request):
    """Export management page. Admin only."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        return RedirectResponse(url="/?error=Admin+access+required", status_code=303)

    pipeline = get_pipeline()
    status = pipeline.get_status()

    return templates.TemplateResponse("export.html", {
        "request": request,
        "status": status
    })


# API routes
@app.post("/api/v1/rag/query", response_model=QueryResponse)
async def api_query(request: Request, query_request: QueryRequest):
    """Query RAG system via API."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        service = get_query_service()
        result = service.query(query_request.query, query_request.force_system)

        return QueryResponse(
            query=result["query"],
            system=result["system"],
            response=result["response"],
            citations=result.get("citations", []),
            filters=result.get("filters"),
            query_time_ms=result.get("query_time_ms", 0)
        )
    except Exception as e:
        logger.error(f"API query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/rag/export")
async def api_export(
    request: Request,
    background_tasks: BackgroundTasks,
    export_request: ExportRequest
):
    """Trigger export pipeline. Admin only."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        since = None
        if export_request.since_date:
            since = datetime.strptime(export_request.since_date, "%Y-%m-%d")

        pipeline = get_pipeline()

        # Run in background
        background_tasks.add_task(
            pipeline.run_full_export,
            since=since,
            batch_size=export_request.batch_size,
            skip_gcs=export_request.skip_gcs,
            skip_gemini=export_request.skip_gemini,
            skip_vertex=export_request.skip_vertex
        )

        return {
            "status": "started",
            "message": "Export pipeline started in background",
            "since_date": export_request.since_date
        }
    except Exception as e:
        logger.error(f"Export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/status")
async def api_status(request: Request):
    """Get RAG system status."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        pipeline = get_pipeline()

        return {
            "database": db.get_statistics(),
            "pipeline": pipeline.get_status(),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/churn")
async def api_churn_report(request: Request, min_score: int = 7, date_range: str = None, start_date: str = None, end_date: str = None):
    """Get churn risk report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Map score to risk level: 7+ = high only, 5+ = high + medium
        risk_level = 'high' if min_score >= 7 else 'medium'

        # Get employee filter for non-admin users
        employee_filter = get_employee_filter(request)

        # Get actual churn risk data from database with date filtering
        churn_data = db.get_churn_risk_data(risk_level, date_range=date_range, start_date=start_date, end_date=end_date, employee_filter=employee_filter)

        if churn_data['total_high_risk'] == 0:
            return {
                "report": "churn_risk",
                "risk_level": risk_level,
                "response": f"No customers with {risk_level} churn risk found.",
                "data": churn_data,
                "generated_at": datetime.now().isoformat()
            }

        # Format the high-risk calls for the prompt
        calls_str = ""
        for call in churn_data['high_risk_calls'][:20]:  # Top 20
            topics = ", ".join(call['topics'][:3]) if call['topics'] else "N/A"
            issues = ", ".join(call['issues'][:2]) if isinstance(call['issues'], list) and call['issues'] else (call['issues'] if call['issues'] else "N/A")

            # Mark unknown values for partial match handling
            customer_name = call['customer_name']
            customer_company = call['customer_company']
            agent = call['agent']

            customer_label = customer_name if customer_name and customer_name != 'Unknown' else f"UNKNOWN (use phone {call['from_number']} or call context)"
            company_label = customer_company if customer_company and customer_company != 'Unknown' else "UNKNOWN COMPANY"
            agent_label = agent if agent and agent != 'Unknown' else f"UNKNOWN AGENT (infer from call context)"

            calls_str += f"""
- Call ID: {call['call_id']}
  Date: {call['call_date']}
  Customer: {customer_label} at {company_label}
  From: {call['from_number']} | To: {call['to_number']}
  Agent: {agent_label}
  Risk Level: {call['risk_level'].upper()}
  Sentiment: {call['sentiment']}
  Quality Score: {call['quality_score']}/10
  Summary: {call['summary'][:150]}...
  Key Issues: {topics}
  Improvement Areas: {issues}
"""

        # Format risk distribution
        risk_dist = churn_data.get('risk_distribution', {})
        risk_dist_str = ", ".join([f"{k}: {v}" for k, v in risk_dist.items()])

        # Format repeat risk companies
        repeat_companies = ""
        for company in churn_data.get('repeat_risk_companies', [])[:5]:
            repeat_companies += f"\n- {company['company']}: {company['risk_count']} at-risk calls ({company['high_count']} high-risk)"

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a Churn Risk Report based on the following ACTUAL DATA.

IMPORTANT: Today's date is {today}. All call dates in this data are from June 2025 onwards. Do NOT include any future dates.

## OVERVIEW:
- Total At-Risk Calls: {churn_data['total_high_risk']}
- Risk Level Filter: {risk_level.upper()}

## RISK DISTRIBUTION:
{risk_dist_str or "No distribution data"}

## COMPANIES WITH MULTIPLE AT-RISK CALLS:
{repeat_companies or "No repeat risk companies found"}

## AT-RISK CALLS (ACTUAL DATA):
{calls_str}

Based on this data, provide:
1. Executive Summary - Overall churn risk situation
2. Top 5 customers requiring IMMEDIATE attention (use their actual names and companies from the data)
3. Common themes causing churn risk
4. Recommended retention actions for each high-priority customer
5. Process improvements to reduce churn risk

CRITICAL RULES:
- Use ONLY the actual customer names, company names, and dates from the data above
- Do NOT invent dates - use the call dates provided (are in 2025 or early 2026)
- Do NOT use placeholder text like [Insert Name]

HANDLING UNKNOWN VALUES:
- When you see "UNKNOWN" for a customer, agent, or company, do NOT skip these entries
- For UNKNOWN customers: Label as "Unknown Caller (partial match - see phone number XXX)" and use the phone number to help identify
- For UNKNOWN agents: Label as "Unknown Agent (best guess from call context)" and try to infer from the summary who might have handled it
- For UNKNOWN companies: Label as "Unknown Company (partial match)" and look for company mentions in the summary
- ALWAYS clearly state when an identification is a PARTIAL MATCH or BEST GUESS, not a confirmed identity
- Include these unknown entries in your analysis - they may represent important at-risk customers we haven't identified yet"""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "churn_risk",
            "risk_level": risk_level,
            "date_range": churn_data.get('date_range', 'all'),
            "data": churn_data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Churn report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/agent/{agent_name}")
async def api_agent_report(request: Request, agent_name: str, date_range: Optional[str] = None):
    """Get agent performance report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Non-admin users can only view their own performance
    user = get_current_user(request)
    if user and user.get('role') != 'admin':
        employee_name = user.get('employee_name')
        if employee_name and agent_name.lower() not in employee_name.lower():
            raise HTTPException(status_code=403, detail="You can only view your own performance reports")

    try:
        db = get_db()

        # Get actual metrics from database
        metrics = db.get_agent_performance(agent_name, date_range)

        if metrics['total_calls'] == 0:
            return {
                "report": "agent_performance",
                "agent": agent_name,
                "date_range": date_range,
                "response": f"No calls found for agent {agent_name} in the specified time period.",
                "metrics": metrics,
                "generated_at": datetime.now().isoformat()
            }

        # Build a detailed prompt with actual data
        date_context = {
            'today': "today",
            'this_week': "the past 7 days",
            'this_month': "the past 30 days"
        }.get(date_range, "all available data")

        # Format sentiment breakdown
        sentiment_str = ", ".join([f"{k}: {v}" for k, v in metrics.get('sentiment_distribution', {}).items()])

        # Format call types
        call_types_str = ", ".join([f"{k}: {v}" for k, v in list(metrics.get('call_types', {}).items())[:5]])

        # Format recent calls
        recent_calls_str = ""
        for call in metrics.get('recent_calls', [])[:5]:
            recent_calls_str += f"\n- Call {call['call_id']} ({call['date']}): {call['company']} - {call['summary'][:100]}... Quality: {call['quality']}/10, Sentiment: {call['sentiment']}"

        # Format strengths and improvements
        strengths_str = "; ".join(metrics.get('common_strengths', [])[:3]) or "None identified"
        improvements_str = "; ".join(metrics.get('common_improvements', [])[:3]) or "None identified"

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a performance report for agent {metrics['agent_name']} based on the following ACTUAL DATA from {date_context}.

IMPORTANT: Today's date is {today}. All call dates are from June 2025 onwards. Do NOT include any future dates.

## PERFORMANCE METRICS (ACTUAL DATA):
- Total Calls Handled: {metrics['total_calls']}
- Average Quality Score: {metrics['avg_quality_score']}/10
- Average Overall Rating: {metrics['avg_overall_rating']}/10
- Average Satisfaction: {metrics['avg_satisfaction']}/10
- Average Empathy Score: {metrics['avg_empathy_score']}/10
- Average Listening Score: {metrics['avg_listening_score']}/10
- Average Closure Score: {metrics['avg_closure_score']}/10
- First Contact Resolution: {metrics['first_contact_resolution_count']} calls

## SENTIMENT BREAKDOWN:
{sentiment_str or "No sentiment data available"}

## CALL TYPES:
{call_types_str or "No call type data available"}

## OBSERVED STRENGTHS:
{strengths_str}

## AREAS FOR IMPROVEMENT:
{improvements_str}

## RECENT CALLS:
{recent_calls_str or "No recent call data"}

Based on this data, provide:
1. A performance summary with specific insights
2. 3 key strengths with examples from the data
3. 3 areas for improvement with specific recommendations
4. Suggested coaching focus for this agent
5. Overall performance rating (Excellent/Good/Needs Improvement/Poor)

CRITICAL: Use the actual numbers and dates provided. Do NOT use placeholder text or invent dates."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "agent_performance",
            "agent": metrics['agent_name'],
            "date_range": date_range,
            "metrics": metrics,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Agent report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/customer/{company_name}")
async def api_customer_report(request: Request, company_name: str, date_range: str = None, start_date: str = None, end_date: str = None):
    """Get customer/company report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Get employee filter for non-admin users
        employee_filter = get_employee_filter(request)

        # Get actual customer data from database with date filtering
        customer_data = db.get_customer_report(company_name, date_range=date_range, start_date=start_date, end_date=end_date, employee_filter=employee_filter)

        if customer_data.get('total_calls', 0) == 0:
            return {
                "report": "customer",
                "company": company_name,
                "response": f"No calls found for company '{company_name}'.",
                "data": customer_data,
                "generated_at": datetime.now().isoformat()
            }

        # Format contacts
        contacts_str = ""
        for contact in customer_data.get('contacts', [])[:5]:
            contacts_str += f"\n- {contact['customer_name']}: {contact['call_count']} calls"

        # Format agents
        agents_str = ""
        for agent in customer_data.get('agents', []):
            agents_str += f"\n- {agent['name']}: {agent['calls']} calls"

        # Format sentiment
        sentiment = customer_data.get('sentiment_distribution', {})
        sentiment_str = ", ".join([f"{k}: {v}" for k, v in sentiment.items()])

        # Format churn risk
        churn = customer_data.get('churn_risk_distribution', {})
        churn_str = ", ".join([f"{k}: {v}" for k, v in churn.items()])

        # Format call types
        call_types = customer_data.get('call_types', {})
        types_str = ", ".join([f"{k}: {v}" for k, v in list(call_types.items())[:5]])

        # Format recent calls
        recent_str = ""
        for call in customer_data.get('recent_calls', [])[:5]:
            recent_str += f"\n- {call['date']}: {call['contact']} spoke with {call['agent']}"
            recent_str += f"\n  Summary: {call['summary'][:100]}..."
            recent_str += f"\n  Sentiment: {call['sentiment']}, Quality: {call['quality']}/10"

        # Format topics
        topics = customer_data.get('common_topics', [])
        topics_str = ", ".join([t['topic'] for t in topics[:5]])

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a Customer Report for {customer_data['company_name']} based on the following ACTUAL DATA.

IMPORTANT: Today's date is {today}. All call dates are from June 2025 onwards. Do NOT include any future dates.

## OVERVIEW:
- Total Calls: {customer_data['total_calls']}
- Unique Contacts: {customer_data['unique_contacts']}
- First Call: {customer_data.get('first_call', 'N/A')}
- Last Call: {customer_data.get('last_call', 'N/A')}
- Avg Quality Score: {customer_data.get('avg_quality', 0)}/10
- Avg Satisfaction: {customer_data.get('avg_satisfaction', 0)}/10

## KEY CONTACTS:
{contacts_str or "No contact data"}

## AGENTS WHO HANDLE THEIR CALLS:
{agents_str or "No agent data"}

## SENTIMENT BREAKDOWN:
{sentiment_str or "No sentiment data"}

## CHURN RISK:
{churn_str or "No churn data"}

## CALL TYPES:
{types_str or "No type data"}

## COMMON TOPICS/ISSUES:
{topics_str or "No topics identified"}

## RECENT CALLS:
{recent_str or "No recent call data"}

Based on this data, provide:
1. Executive Summary - Overall relationship health with this customer
2. Key contacts and their engagement patterns
3. Common issues they face (based on topics and call types)
4. Risk assessment (based on sentiment and churn risk)
5. Recommended actions to improve this customer relationship
6. Suggested proactive outreach topics

CRITICAL: Use the actual data and dates provided. Do NOT use placeholder text or invent dates."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "customer",
            "company": customer_data['company_name'],
            "date_range": customer_data.get('date_range', 'all'),
            "data": customer_data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Customer report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/customers")
async def api_list_customers(request: Request, limit: int = 50):
    """Get list of customer companies."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        companies = db.get_customer_companies(limit)

        return {
            "customers": companies,
            "total": len(companies)
        }
    except Exception as e:
        logger.error(f"List customers error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/quality")
async def api_quality_report(request: Request, focus: str = "low_quality", date_range: str = None, start_date: str = None, end_date: str = None):
    """Get call quality report with actual data.

    Args:
        focus: 'low_quality', 'trends', or 'by_type'
        date_range: 'last_30', 'mtd', 'qtd', 'ytd', or None for all time
        start_date: Custom start date (YYYY-MM-DD)
        end_date: Custom end date (YYYY-MM-DD)
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Get employee filter for non-admin users
        employee_filter = get_employee_filter(request)

        # Get actual quality data from database
        quality_data = db.get_quality_report_data(focus, date_range, start_date, end_date, employee_filter=employee_filter)

        # Format the low quality calls for the prompt
        calls_str = ""
        for call in quality_data.get('low_quality_calls', [])[:15]:
            topics = ", ".join(call['topics'][:3]) if call['topics'] else "N/A"
            improvements = "; ".join(call['improvements'][:3]) if call['improvements'] else "None identified"

            # Mark unknown values for partial match handling
            employee = call['employee_name']
            customer = call['customer_name']
            company = call['customer_company']

            employee_label = employee if employee and employee not in ('Unknown', 'Unknown Agent', '') else f"UNKNOWN AGENT (infer from context)"
            customer_label = customer if customer and customer != 'Unknown' else f"UNKNOWN CALLER (phone: {call['from_number']})"
            company_label = company if company and company != 'Unknown' else "UNKNOWN COMPANY"

            calls_str += f"""
- Date: {call['call_date']}
  PC Recruiter Agent: {employee_label}
  Customer: {customer_label} at {company_label}
  Phone: From {call['from_number']} To {call['to_number']}
  Quality Score: {call['quality_score']}/10
  Why Low Quality: {call['quality_reasoning'][:200]}...
  Sentiment: {call['sentiment']}
  Call Type: {call['call_type']}
  Summary: {call['summary'][:150]}...
  Topics: {topics}
  Suggested Improvements: {improvements}
"""

        # Format quality by agent
        agent_str = ""
        for agent in quality_data.get('quality_by_agent', [])[:10]:
            agent_str += f"\n- {agent['agent']}: {agent['total_calls']} calls, Avg Quality: {agent['avg_quality']}/10, Low Quality: {agent['low_quality_count']}, High Quality: {agent['high_quality_count']}"

        # Format quality by call type
        type_str = ""
        for ct in quality_data.get('quality_by_call_type', [])[:8]:
            type_str += f"\n- {ct['call_type']}: {ct['total_calls']} calls, Avg Quality: {ct['avg_quality']}/10, Low Quality: {ct['low_quality_count']}"

        # Format trends
        trends_str = ""
        for week in quality_data.get('weekly_trends', [])[:8]:
            trends_str += f"\n- Week of {week['week']}: {week['total']} calls, Avg Quality: {week['avg_quality']}, Low: {week['low_quality']}, High: {week['high_quality']}"

        # Format distribution
        dist = quality_data.get('quality_distribution', {})
        dist_str = ", ".join([f"{k}: {v}" for k, v in dist.items()])

        # Format topics
        topics_list = quality_data.get('low_quality_topics', [])
        topics_str = ", ".join([f"{t['topic']} ({t['count']})" for t in topics_list[:10]])

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        # Date range context for prompt
        if start_date and end_date:
            date_range_label = f"{start_date} to {end_date}"
        else:
            date_range_label = {
                'last_30': 'Last 30 Days',
                'mtd': 'Month to Date',
                'qtd': 'Quarter to Date',
                'ytd': 'Year to Date',
                None: 'All Time'
            }.get(date_range, 'All Time')

        prompt = f"""Generate a Call Quality Analysis Report based on the following ACTUAL DATA.

IMPORTANT: Today's date is {today}. All call dates in this data are from June 2025 onwards. Do NOT include any future dates.
DATE RANGE: {date_range_label}

## OVERALL QUALITY METRICS:
- Date Range: {date_range_label}
- Average Quality Score: {quality_data.get('avg_quality', 0)}/10
- Total Calls Analyzed: {quality_data.get('total_calls_with_quality', 0)}
- Low Quality Calls (< 5): {quality_data.get('total_low_quality', 0)}

## QUALITY DISTRIBUTION:
{dist_str or "No distribution data"}

## PC RECRUITER AGENTS - QUALITY BREAKDOWN:
{agent_str or "No agent data available"}

## QUALITY BY CALL TYPE:
{type_str or "No call type data"}

## WEEKLY QUALITY TRENDS (Last 8 weeks):
{trends_str or "No trend data"}

## COMMON TOPICS IN LOW QUALITY CALLS:
{topics_str or "No topics identified"}

## LOW QUALITY CALLS (ACTUAL DATA):
{calls_str}

Based on this ACTUAL data, provide:
1. Executive Summary - Overall call quality health
2. Root causes of low quality calls (use actual call examples with their real dates)
3. Agents who need coaching (use actual agent names and their scores)
4. Call types that need process improvement
5. Specific training recommendations based on the quality reasoning
6. Trends analysis - is quality improving or declining?

CRITICAL RULES:
- Use ONLY the actual agent names, customer names, companies, and dates from the data above
- Do NOT invent dates - use the call dates provided (are in 2025 or early 2026)
- Do NOT use placeholder text like [Insert Name]

HANDLING UNKNOWN VALUES:
- When you see "UNKNOWN AGENT", "UNKNOWN CALLER", or "UNKNOWN COMPANY", do NOT skip these entries
- For UNKNOWN agents: Label as "Unknown Agent (best guess from call context: [your inference])" - use the summary to try identifying who handled the call
- For UNKNOWN callers: Label as "Unknown Caller (partial match - phone: XXX)" and use the phone number as identifier
- For UNKNOWN companies: Label as "Unknown Company (partial match)" and check the summary for company mentions
- ALWAYS clearly state when an identification is a PARTIAL MATCH or BEST GUESS, not a confirmed identity
- Include these unknown entries in quality analysis - they represent calls that need attention regardless of identity"""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "quality",
            "focus": focus,
            "data": quality_data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Quality report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/sentiment")
async def api_sentiment_report(request: Request, analysis: str = "negative", date_range: str = None, start_date: str = None, end_date: str = None):
    """Get sentiment analysis report with actual data.

    Args:
        analysis: 'negative', 'positive', 'all', or 'trends'
        date_range: 'last_30', 'mtd', 'qtd', 'ytd', or None for all time
        start_date: Custom start date (YYYY-MM-DD)
        end_date: Custom end date (YYYY-MM-DD)
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Get employee filter for non-admin users
        employee_filter = get_employee_filter(request)

        # Get actual sentiment data from database
        sentiment_data = db.get_sentiment_report_data(analysis, date_range, start_date, end_date, employee_filter=employee_filter)

        if sentiment_data.get('total_matching', 0) == 0:
            return {
                "report": "sentiment",
                "analysis_type": analysis,
                "response": f"No calls found matching the '{analysis}' sentiment filter.",
                "data": sentiment_data,
                "generated_at": datetime.now().isoformat()
            }

        # Format the calls for the prompt
        calls_str = ""
        for call in sentiment_data['calls'][:15]:  # Top 15 for prompt
            topics = ", ".join(call['topics'][:3]) if call['topics'] else "N/A"

            # Mark unknown values for partial match handling
            employee = call['employee_name']
            customer = call['customer_name']
            company = call['customer_company']

            employee_label = employee if employee and employee not in ('Unknown', 'Unknown Agent', '') else f"UNKNOWN AGENT (infer from context)"
            customer_label = customer if customer and customer != 'Unknown' else f"UNKNOWN CALLER (phone: {call['from_number']})"
            company_label = company if company and company != 'Unknown' else "UNKNOWN COMPANY"

            calls_str += f"""
- Date: {call['call_date']}
  PC Recruiter Agent: {employee_label}
  Customer: {customer_label} at {company_label}
  Phone: From {call['from_number']} To {call['to_number']}
  Sentiment: {call['sentiment']} (Quality: {call['quality_score']}/10)
  Reasoning: {call['sentiment_reasoning'][:200]}...
  Call Type: {call['call_type']}
  Summary: {call['summary'][:150]}...
  Topics: {topics}
  Churn Risk: {call['churn_risk']}
"""

        # Format sentiment by agent
        agent_str = ""
        for agent in sentiment_data.get('sentiment_by_agent', [])[:10]:
            agent_str += f"\n- {agent['agent']}: {agent['total_calls']} total calls, {agent['negative_calls']} negative, {agent['positive_calls']} positive (Avg Quality: {agent['avg_quality']})"

        # Format sentiment by customer
        customer_str = ""
        for cust in sentiment_data.get('sentiment_by_customer', [])[:10]:
            customer_str += f"\n- {cust['company']}: {cust['total_calls']} calls, {cust['negative_calls']} negative, {cust['positive_calls']} positive"

        # Format topics
        topics_list = sentiment_data.get('negative_sentiment_topics', [])
        topics_str = ", ".join([f"{t['topic']} ({t['count']})" for t in topics_list[:10]])

        # Format trends
        trends_str = ""
        for week in sentiment_data.get('weekly_trends', [])[:8]:
            trends_str += f"\n- Week of {week['week']}: {week['total']} calls - {week['negative']} negative, {week['positive']} positive, {week['neutral']} neutral"

        # Format overall distribution
        dist = sentiment_data.get('sentiment_distribution', {})
        dist_str = ", ".join([f"{k}: {v}" for k, v in dist.items()])

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        # Date range context for prompt
        if start_date and end_date:
            date_range_label = f"{start_date} to {end_date}"
        else:
            date_range_label = {
                'last_30': 'Last 30 Days',
                'mtd': 'Month to Date',
                'qtd': 'Quarter to Date',
                'ytd': 'Year to Date',
                None: 'All Time'
            }.get(date_range, 'All Time')

        prompt = f"""Generate a Sentiment Analysis Report based on the following ACTUAL DATA from our call center.

IMPORTANT: Today's date is {today}. Do NOT include any dates in the future. All call dates in this data are from June 2025 onwards.
DATE RANGE: {date_range_label}

## OVERALL SENTIMENT DISTRIBUTION ({date_range_label}):
{dist_str}

## PC RECRUITER AGENTS - SENTIMENT BREAKDOWN:
{agent_str or "No agent data available"}

## CUSTOMER COMPANIES WITH NEGATIVE SENTIMENT:
{customer_str or "No customer company data"}

## COMMON TOPICS IN NEGATIVE CALLS:
{topics_str or "No topics identified"}

## WEEKLY SENTIMENT TRENDS:
{trends_str or "No trend data"}

## SAMPLE NEGATIVE SENTIMENT CALLS (ACTUAL DATA):
{calls_str}

Based on this ACTUAL data, provide:
1. Executive Summary - Overall customer sentiment health
2. Top 3 drivers of negative sentiment (use actual topics and call examples with their real dates)
3. Agents who may need coaching (use actual agent names from the data)
4. Customer companies at risk (use actual company names from the data)
5. Recommended actions to improve sentiment
6. Trends analysis - are things improving or getting worse?

CRITICAL RULES:
- Use ONLY the actual names, companies, and dates from the data above
- Do NOT invent dates - use the call dates provided (are in 2025 or early 2026)
- Do NOT use placeholder text like [Insert Name]
- Reference specific calls by their actual date, agent name, and customer company

HANDLING UNKNOWN VALUES:
- When you see "UNKNOWN AGENT", "UNKNOWN CALLER", or "UNKNOWN COMPANY", do NOT skip these entries
- For UNKNOWN agents: Label as "Unknown Agent (best guess from call context: [your inference])" - try to identify from the call summary
- For UNKNOWN callers: Label as "Unknown Caller (partial match - phone: XXX)" and use the phone number as identifier
- For UNKNOWN companies: Label as "Unknown Company (partial match)" and check the summary for company mentions
- ALWAYS clearly state when an identification is a PARTIAL MATCH or BEST GUESS, not a confirmed identity
- These unknown entries may represent important patterns - include them in your analysis"""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "sentiment",
            "analysis_type": analysis,
            "data": sentiment_data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Sentiment report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/routing/explain")
async def api_routing_explain(request: Request, query: str):
    """Explain how a query would be routed."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    router = QueryRouter()
    system, filters = router.route(query)

    return {
        "query": query,
        "routed_to": system.value,
        "filters_extracted": filters
    }


# ==========================================
# KNOWLEDGE BASE ROUTES (Simple - searches RAG directly)
# ==========================================

def get_kb_service():
    """Get Simple Knowledge Base service instance"""
    from rag_integration.services.kb_simple import SimpleKBService
    return SimpleKBService()


@app.get("/knowledge-base", response_class=HTMLResponse)
async def knowledge_base_page(request: Request):
    """Knowledge Base main page with search"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    kb = get_kb_service()
    stats = kb.get_stats(days=30)
    recent_searches = kb.get_recent_searches(limit=10)

    return templates.TemplateResponse("knowledge_base.html", {
        "request": request,
        "stats": stats,
        "recent_searches": recent_searches
    })


@app.get("/knowledge-base/search")
async def kb_search_get(
    request: Request,
    q: str = None,
    category: str = None,
    source: str = None,
    employee: str = None,
    offset: int = 0,
    sort: str = "recent",
    ajax: str = None
):
    """KB search page (GET - for links and bookmarks)"""
    from fastapi.responses import JSONResponse

    if not check_auth(request):
        if ajax == '1':
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        return RedirectResponse(url="/login", status_code=303)

    kb = get_kb_service()
    session_id = request.cookies.get('session', 'anonymous')

    # Validate sort parameter
    if sort and sort not in ['recent', 'rating']:
        sort = None

    # AJAX request for pagination - return JSON
    if ajax == '1' and q:
        filters = {}
        if source:
            filters['source'] = source
        if employee:
            filters['employee'] = employee
        if category:
            filters['category'] = category

        search_results = kb.search(q, agent_id=session_id, filters=filters if filters else None, offset=offset, sort=sort)
        return JSONResponse({
            "results": search_results.get('results', []),
            "total_matches": search_results.get('total_matches', 0),
            "result_count": search_results.get('result_count', 0)
        })

    # Regular HTML response
    stats = kb.get_stats(days=30)
    search_results = None
    active_filters = {}
    if q:
        # Build filters dict from query params
        filters = {}
        if source:
            filters['source'] = source
            active_filters['source'] = source
        if employee:
            filters['employee'] = employee
            active_filters['employee'] = employee
        if category:
            filters['category'] = category
            active_filters['category'] = category

        search_results = kb.search(q, agent_id=session_id, filters=filters if filters else None, sort=sort)

    return templates.TemplateResponse("kb_search.html", {
        "request": request,
        "stats": stats,
        "search_results": search_results,
        "query": q or "",
        "category": category,
        "active_filters": active_filters,
        "sort": sort
    })


@app.post("/knowledge-base/search", response_class=HTMLResponse)
async def kb_search_submit(
    request: Request,
    query: str = Form(...)
):
    """Process KB search from web form (POST)"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    kb = get_kb_service()
    session_id = request.cookies.get('session', 'anonymous')

    results = kb.search(query, agent_id=session_id)
    stats = kb.get_stats(days=30)

    return templates.TemplateResponse("kb_search.html", {
        "request": request,
        "stats": stats,
        "search_results": results,
        "query": query,
        "active_filters": {},
        "sort": None
    })


@app.get("/knowledge-base/stats", response_class=HTMLResponse)
async def kb_stats_page(request: Request):
    """KB usage statistics page"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    kb = get_kb_service()
    stats = kb.get_stats(days=30)
    recent_searches = kb.get_recent_searches(limit=50)

    return templates.TemplateResponse("kb_stats.html", {
        "request": request,
        "stats": stats,
        "recent_searches": recent_searches
    })


# Knowledge Base API Endpoints

@app.get("/api/v1/kb/search")
async def api_kb_search(
    request: Request,
    q: str
):
    """API: Search knowledge base using RAG"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    kb = get_kb_service()
    session_id = request.cookies.get('session', 'anonymous')

    results = kb.search(q, agent_id=session_id)
    return results


@app.post("/api/v1/kb/feedback")
async def api_kb_feedback(
    request: Request,
    search_id: int = Form(...),
    helpful: bool = Form(...),
    result_index: int = Form(None),
    comment: str = Form(None)
):
    """API: Submit feedback for a search result"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    kb = get_kb_service()
    session_id = request.cookies.get('session', 'anonymous')

    result = kb.submit_feedback(
        search_id=search_id,
        helpful=helpful,
        result_index=result_index,
        comment=comment,
        agent_id=session_id
    )

    return result


@app.get("/api/v1/kb/stats")
async def api_kb_stats(
    request: Request,
    days: int = 30
):
    """API: Get KB usage statistics"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    kb = get_kb_service()
    stats = kb.get_stats(days=days)

    return stats


@app.post("/api/v1/kb/rate")
async def api_kb_rate(
    request: Request,
    qa_id: str = Form(...),
    source_type: str = Form(...),
    rating: int = Form(...),
    search_query: str = Form(None)
):
    """API: Rate a knowledge base answer (1-5 stars)"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    user = get_current_user(request)
    user_id = user.get('username', 'anonymous') if user else 'anonymous'

    # Use SimpleKBService for write operations (DatabaseReader is read-only)
    kb = get_kb_service()
    try:
        with kb.get_connection() as conn:
            with conn.cursor() as cur:
                # Insert rating
                cur.execute("""
                    INSERT INTO kb_ratings (qa_id, source_type, rating, search_query, user_id)
                    VALUES (%s, %s, %s, %s, %s)
                """, (qa_id, source_type, rating, search_query, user_id))

                # Update avg_rating in kb_freshdesk_qa if it's a freshdesk result
                if source_type == 'freshdesk':
                    # Extract ticket_id from qa_id (e.g., 'fd_123456' -> 123456)
                    ticket_id = qa_id.replace('fd_', '') if qa_id.startswith('fd_') else qa_id

                    cur.execute("""
                        UPDATE kb_freshdesk_qa
                        SET avg_rating = (
                            SELECT AVG(rating)::DECIMAL(3,2)
                            FROM kb_ratings
                            WHERE qa_id = %s AND source_type = 'freshdesk'
                        ),
                        rating_count = (
                            SELECT COUNT(*)
                            FROM kb_ratings
                            WHERE qa_id = %s AND source_type = 'freshdesk'
                        )
                        WHERE qa_id = %s OR ticket_id::text = %s
                    """, (qa_id, qa_id, qa_id, ticket_id))

        logger.info(f"Rating saved: {qa_id} = {rating} stars by {user_id}")

        return {
            "success": True,
            "qa_id": qa_id,
            "rating": rating,
            "message": "Thank you for rating!"
        }

    except Exception as e:
        logger.error(f"Error saving rating: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/kb/rating/{qa_id}")
async def api_kb_get_rating(request: Request, qa_id: str):
    """API: Get average rating for a Q/A"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    db = get_db()
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        AVG(rating)::DECIMAL(3,2) as avg_rating,
                        COUNT(*) as rating_count
                    FROM kb_ratings
                    WHERE qa_id = %s
                """, (qa_id,))
                result = cur.fetchone()

                return {
                    "qa_id": qa_id,
                    "avg_rating": float(result['avg_rating']) if result['avg_rating'] else None,
                    "rating_count": result['rating_count'] or 0
                }

    except Exception as e:
        logger.error(f"Error getting rating: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# FRESHDESK KB INTEGRATION (Admin Only)
# ==========================================

def get_freshdesk_scraper():
    """Get Freshdesk scraper instance."""
    from rag_integration.services.freshdesk_scraper import FreshdeskScraper
    return FreshdeskScraper()


@app.get("/admin/freshdesk", response_class=HTMLResponse)
async def freshdesk_admin_page(request: Request):
    """Freshdesk sync admin page"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        scraper = get_freshdesk_scraper()
        qa_count = scraper.get_qa_count()
        sync_history = scraper.get_sync_history(limit=10)
        connection_test = scraper.test_connection()
    except Exception as e:
        qa_count = 0
        sync_history = []
        connection_test = {'success': False, 'error': str(e)}

    return templates.TemplateResponse("freshdesk_admin.html", {
        "request": request,
        "qa_count": qa_count,
        "sync_history": sync_history,
        "connection_test": connection_test
    })


@app.post("/admin/freshdesk/sync")
async def freshdesk_sync(
    request: Request,
    background_tasks: BackgroundTasks,
    days: int = Form(30),
    max_tickets: int = Form(100)
):
    """Start Freshdesk sync (runs in background)"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    def run_sync():
        try:
            scraper = get_freshdesk_scraper()
            stats = scraper.sync_tickets(since_days=days, max_tickets=max_tickets)
            logger.info(f"Freshdesk sync complete: {stats}")
        except Exception as e:
            logger.error(f"Freshdesk sync failed: {e}")

    background_tasks.add_task(run_sync)

    return RedirectResponse(url="/admin/freshdesk?started=1", status_code=303)


@app.get("/api/v1/kb/freshdesk/test")
async def api_freshdesk_test(request: Request):
    """API: Test Freshdesk connection"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    scraper = get_freshdesk_scraper()
    return scraper.test_connection()


@app.get("/api/v1/kb/freshdesk/stats")
async def api_freshdesk_stats(request: Request):
    """API: Get Freshdesk Q&A stats"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    scraper = get_freshdesk_scraper()
    return {
        "qa_count": scraper.get_qa_count(),
        "sync_history": scraper.get_sync_history(limit=5)
    }


@app.post("/api/v1/kb/freshdesk/sync")
async def api_freshdesk_sync(
    request: Request,
    background_tasks: BackgroundTasks,
    days: int = 30,
    max_tickets: int = 100
):
    """API: Start Freshdesk sync"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    def run_sync():
        try:
            scraper = get_freshdesk_scraper()
            stats = scraper.sync_tickets(since_days=days, max_tickets=max_tickets)
            logger.info(f"Freshdesk sync complete: {stats}")
        except Exception as e:
            logger.error(f"Freshdesk sync failed: {e}")

    background_tasks.add_task(run_sync)

    return {"status": "started", "days": days, "max_tickets": max_tickets}


@app.post("/api/v1/kb/freshdesk/export")
async def api_freshdesk_export(
    request: Request,
    background_tasks: BackgroundTasks
):
    """API: Export Freshdesk Q&A to JSONL for Vertex AI RAG"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    def run_export():
        try:
            scraper = get_freshdesk_scraper()
            result = scraper.export_to_jsonl()
            logger.info(f"Freshdesk JSONL export complete: {result}")
        except Exception as e:
            logger.error(f"Freshdesk export failed: {e}")

    background_tasks.add_task(run_export)

    return {"status": "started", "message": "JSONL export started"}


@app.post("/admin/freshdesk/export")
async def freshdesk_export(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Admin: Export Freshdesk Q&A to JSONL"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    def run_export():
        try:
            scraper = get_freshdesk_scraper()
            result = scraper.export_to_jsonl()
            logger.info(f"Freshdesk JSONL export complete: {result}")
        except Exception as e:
            logger.error(f"Freshdesk export failed: {e}")

    background_tasks.add_task(run_export)

    return RedirectResponse(url="/admin/freshdesk?exported=1", status_code=303)


# ==========================================
# ADMIN ROUTES (User Management)
# ==========================================

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    """Admin: User management page"""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    auth = get_auth_service()
    users = auth.list_users()

    # Add Fathom key status to each user
    import psycopg2
    conn = psycopg2.connect(os.getenv('RAG_DATABASE_URL', os.getenv('DATABASE_URL', '')))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT employee_email FROM fathom_api_keys WHERE is_active = TRUE")
            fathom_emails = {row[0].lower() for row in cur.fetchall()}

        for u in users:
            u['has_fathom_key'] = u.get('email', '').lower() in fathom_emails if u.get('email') else False
    finally:
        conn.close()

    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "user": get_current_user(request),
        "users": users
    })


@app.post("/admin/users/{username}/reset-password")
async def admin_reset_user_password(request: Request, username: str):
    """Admin: Reset a user's password to default"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    auth = get_auth_service()
    admin_user = get_current_user(request)
    result = auth.admin_reset_password(admin_user, username)

    if result['success']:
        return RedirectResponse(url=f"/admin/users?reset={username}", status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed to reset password'))


@app.post("/admin/users/sync")
async def admin_sync_users(request: Request):
    """Admin: Sync users from employee list"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    auth = get_auth_service()
    result = auth.sync_users_from_employees()

    return RedirectResponse(url=f"/admin/users?synced={result['created']}", status_code=303)


@app.post("/admin/users/{username}/role")
async def admin_change_user_role(request: Request, username: str, role: str = Form(...)):
    """Admin: Change a user's role"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    auth = get_auth_service()
    admin_user = get_current_user(request)
    result = auth.change_user_role(admin_user, username, role)

    if result['success']:
        return RedirectResponse(url=f"/admin/users?role_changed={username}", status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed to change role'))


@app.post("/admin/users/{username}/toggle-active")
async def admin_toggle_user_active(request: Request, username: str):
    """Admin: Toggle a user's active status"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    auth = get_auth_service()
    admin_user = get_current_user(request)
    result = auth.toggle_user_active(admin_user, username)

    if result['success']:
        return RedirectResponse(url=f"/admin/users?toggled={username}", status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed to toggle status'))


@app.post("/admin/users/add")
async def admin_add_user(
    request: Request,
    display_name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    role: str = Form("user"),
    employee_name: str = Form(None),
    password: str = Form("changeme123"),
    fathom_api_key: str = Form(None)
):
    """Admin: Add a new user"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    import psycopg2
    conn = psycopg2.connect(os.getenv('RAG_DATABASE_URL',
        os.getenv('DATABASE_URL', '')))

    try:
        with conn.cursor() as cur:
            # Simple password hash format
            password_hash = f"pbkdf2:sha256:600000$user${password}"

            cur.execute("""
                INSERT INTO users (username, password_hash, display_name, email, role, employee_name, is_active, must_change_password)
                VALUES (%s, %s, %s, %s, %s, %s, true, true)
            """, (username, password_hash, display_name, email, role, employee_name))

            # Add Fathom API key if provided
            if fathom_api_key and fathom_api_key.strip():
                try:
                    from src.fathom.key_manager import FathomKeyManager
                    km = FathomKeyManager()
                    km.add_employee(
                        employee_name=display_name,
                        employee_email=email,
                        api_key=fathom_api_key.strip(),
                        team=None,
                        is_admin=(role == 'admin')
                    )
                except Exception as fathom_err:
                    logger.warning(f"Failed to add Fathom key: {fathom_err}")

            conn.commit()

        return RedirectResponse(url=f"/admin/users?message=User {username} added", status_code=303)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.post("/admin/users/edit")
async def admin_edit_user(
    request: Request,
    user_id: int = Form(...),
    display_name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    employee_name: str = Form(None),
    is_active: str = Form(None),
    fathom_api_key: str = Form(None)
):
    """Admin: Edit an existing user"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    import psycopg2
    conn = psycopg2.connect(os.getenv('RAG_DATABASE_URL',
        os.getenv('DATABASE_URL', '')))

    try:
        with conn.cursor() as cur:
            active = is_active == 'true'
            cur.execute("""
                UPDATE users
                SET display_name = %s, email = %s, role = %s, employee_name = %s, is_active = %s
                WHERE id = %s
            """, (display_name, email, role, employee_name, active, user_id))

            # Update Fathom API key if provided (non-empty)
            if fathom_api_key and fathom_api_key.strip():
                try:
                    from src.fathom.key_manager import FathomKeyManager
                    km = FathomKeyManager()
                    km.add_employee(
                        employee_name=display_name,
                        employee_email=email,
                        api_key=fathom_api_key.strip(),
                        team=None,
                        is_admin=(role == 'admin')
                    )
                except Exception as fathom_err:
                    logger.warning(f"Failed to update Fathom key: {fathom_err}")

            conn.commit()

        return RedirectResponse(url=f"/admin/users?message=User updated", status_code=303)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.post("/admin/users/{username}/delete")
async def admin_delete_user(request: Request, username: str):
    """Admin: Delete a user"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    if username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot delete admin user")

    import psycopg2
    conn = psycopg2.connect(os.getenv('RAG_DATABASE_URL',
        os.getenv('DATABASE_URL', '')))

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
            conn.commit()

        return RedirectResponse(url=f"/admin/users?message=User {username} deleted", status_code=303)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.get("/api/v1/admin/users")
async def api_admin_list_users(request: Request):
    """API: List all users (admin only)"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    auth = get_auth_service()
    users = auth.list_users()

    return {"users": users, "count": len(users)}


# ==========================================
# PIPELINE STATUS & MONITORING (Admin)
# ==========================================

def get_pipeline_status():
    """Get pipeline status from status file."""
    import json
    from pathlib import Path

    status_file = Path("/var/www/call-recording-system/data/pipeline_status.json")
    alerts_dir = Path("/var/www/call-recording-system/data/alerts")

    status = {
        "has_errors": False,
        "status": "OK",
        "last_check": None,
        "message": None
    }

    # Read status file
    if status_file.exists():
        try:
            with open(status_file) as f:
                status = json.load(f)
        except:
            pass

    # Get recent alerts
    alerts = []
    if alerts_dir.exists():
        alert_files = sorted(alerts_dir.glob("*.txt"), reverse=True)[:5]
        for af in alert_files:
            try:
                alerts.append({
                    "timestamp": af.stem.replace("pipeline_alert_", "").replace("_", " "),
                    "content": af.read_text()[:2000]
                })
            except:
                pass

    return status, alerts


def get_pipeline_jobs_status():
    """Get status of each pipeline job."""
    from datetime import datetime
    from pathlib import Path

    log_dir = Path("/var/www/call-recording-system/logs")
    today = datetime.now().strftime("%Y%m%d")
    current_hour = int(datetime.now().strftime("%H"))

    jobs = [
        {"time": "6:00am/pm", "name": "RingCentral Download", "description": "Fetch all calls + recordings", "log_pattern": "ringcentral_v2_", "hours": [6, 18]},
        {"time": "6:30am/pm", "name": "Transcription", "description": "Transcribe new recordings", "log_pattern": "transcription_v2_", "hours": [6, 18]},
        {"time": "7:30am/pm", "name": "AI Layers 1-5", "description": "Generate insights, sentiment, recommendations", "log_pattern": "ai_layers_", "hours": [7, 19]},
        {"time": "8:30am/pm", "name": "Vertex RAG Export", "description": "Upload analyzed calls to RAG", "log_pattern": "vertex_rag_export_", "hours": [8, 20]},
        {"time": "9:00am/pm", "name": "Freshdesk Pipeline", "description": "Sync, enrich, export KB", "log_pattern": "freshdesk_pipeline_", "hours": [9, 21]},
    ]

    for job in jobs:
        log_file = log_dir / f"{job['log_pattern']}{today}.log"

        # Check if job should have run
        should_have_run = any(current_hour >= (h + 1) for h in job["hours"])

        if not should_have_run:
            job["status"] = "pending"
        elif log_file.exists():
            # Check log for errors
            content = log_file.read_text()
            if any(x in content.lower() for x in ["error", "failed", "exception", "traceback"]):
                if "errors.*0" in content or "no errors" in content.lower():
                    job["status"] = "ok"
                else:
                    job["status"] = "error"
            elif any(x in content.lower() for x in ["complete", "success", "done"]):
                job["status"] = "ok"
            else:
                job["status"] = "unknown"
        else:
            job["status"] = "error"

    return jobs


@app.get("/admin/pipeline", response_class=HTMLResponse)
async def admin_pipeline_page(request: Request):
    """Pipeline status page for admins."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        return RedirectResponse(url="/", status_code=303)

    import subprocess

    status, alerts = get_pipeline_status()
    jobs = get_pipeline_jobs_status()

    # Get database stats
    db_status = {"connected": False}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transcripts")
        db_status["transcripts"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM insights")
        db_status["with_insights"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
        db_status["freshdesk_qa"] = cur.fetchone()[0]
        db_status["connected"] = True
        conn.close()
    except Exception as e:
        db_status["error"] = str(e)

    # Get disk usage
    try:
        result = subprocess.run(["df", "-h", "/var/www/call-recording-system"],
                              capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            parts = lines[1].split()
            disk_usage = int(parts[4].replace("%", ""))
            disk_used = parts[2]
            disk_total = parts[1]
        else:
            disk_usage, disk_used, disk_total = 0, "?", "?"
    except:
        disk_usage, disk_used, disk_total = 0, "?", "?"

    return templates.TemplateResponse("admin_pipeline.html", {
        "request": request,
        "status": status,
        "jobs": jobs,
        "alerts": alerts,
        "db_status": db_status,
        "disk_usage": disk_usage,
        "disk_used": disk_used,
        "disk_total": disk_total,
        "user": get_current_user(request)
    })


@app.get("/api/v1/admin/pipeline/status")
async def api_pipeline_status(request: Request):
    """API: Get pipeline status (admin only)."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    status, alerts = get_pipeline_status()
    jobs = get_pipeline_jobs_status()

    return {
        "status": status,
        "jobs": jobs,
        "alerts": [a["timestamp"] for a in alerts]
    }


# ==========================================
# SALES & COMPETITIVE INTELLIGENCE REPORTS (Layer 5)
# ==========================================

@app.get("/sales-intelligence", response_class=HTMLResponse)
async def sales_intelligence_page(request: Request):
    """Sales & Competitive Intelligence reports page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # Use canonical employee list from config
    agents = get_canonical_employee_list()

    return templates.TemplateResponse("sales_intelligence.html", {
        "request": request,
        "agents": agents,
        "user": get_current_user(request)
    })


@app.get("/api/v1/rag/reports/sales-pipeline")
async def api_sales_pipeline_report(
    request: Request,
    min_score: int = 5,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get sales pipeline report from Layer 5 buying signals."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        employee_filter = get_employee_filter(request)

        data = db.get_sales_pipeline_data(
            min_score=min_score,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date,
            employee_filter=employee_filter
        )

        if data['total_opportunities'] == 0:
            return {
                "report": "sales_pipeline",
                "response": "No sales opportunities found matching the criteria.",
                "data": data,
                "generated_at": datetime.now().isoformat()
            }

        # Build prompt for AI analysis
        opps_str = ""
        for opp in data['opportunities'][:15]:
            signals = ", ".join(opp['buying_signals'][:3]) if opp['buying_signals'] else "None detected"
            opps_str += f"""
- Date: {opp['call_date']}
  Customer: {opp['customer_name'] or 'Unknown'} at {opp['customer_company'] or 'Unknown'}
  Agent: {opp['employee_name'] or 'Unknown'}
  Score: {opp['sales_opportunity_score']}/10
  Buying Signals: {signals}
  Summary: {(opp['summary'] or '')[:150]}...
"""

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a Sales Pipeline Report based on the following ACTUAL DATA.

Today's date: {today}

## OVERVIEW:
- Total Opportunities: {data['total_opportunities']}
- Hot Opportunities (Score 8-10): {data['hot_opportunities']}
- Warm Opportunities (Score 5-7): {data['warm_opportunities']}

## DISTRIBUTION:
{data['by_signal_strength']}

## TOP SALES OPPORTUNITIES:
{opps_str}

Based on this data, provide:
1. Executive Summary of the sales pipeline
2. Top 5 highest priority opportunities with specific next steps
3. Common buying signals detected
4. Recommended follow-up actions for the sales team
5. Any patterns or trends in the opportunities

Use the actual customer names, dates, and scores from the data."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "sales_pipeline",
            "data": data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Sales pipeline report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/competitor-intelligence")
async def api_competitor_intelligence_report(
    request: Request,
    competitor: str = None,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get competitor intelligence report from Layer 5 data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        employee_filter = get_employee_filter(request)

        data = db.get_competitor_intelligence_data(
            competitor=competitor,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date,
            employee_filter=employee_filter
        )

        if data['total_mentions'] == 0:
            return {
                "report": "competitor_intelligence",
                "response": "No competitor mentions found in the call data.",
                "data": data,
                "generated_at": datetime.now().isoformat()
            }

        # Build prompt
        mentions_str = ""
        for mention in data['mentions'][:10]:
            comps = ", ".join(mention['competitors']) if mention['competitors'] else "None"
            mentions_str += f"""
- Date: {mention['call_date']}
  Customer: {mention['customer_name'] or 'Unknown'} at {mention['customer_company'] or 'Unknown'}
  Competitors Mentioned: {comps}
  Summary: {(mention['summary'] or '')[:150]}...
"""

        counts_str = "\n".join([f"- {comp}: {count} mentions" for comp, count in list(data['competitor_counts'].items())[:10]])

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a Competitor Intelligence Report based on the following ACTUAL DATA.

Today's date: {today}

## OVERVIEW:
- Total Calls with Competitor Mentions: {data['total_mentions']}

## COMPETITOR MENTION COUNTS:
{counts_str}

## SAMPLE COMPETITOR MENTIONS:
{mentions_str}

Based on this data, provide:
1. Executive Summary of competitive landscape
2. Top 3 most mentioned competitors and what customers are saying
3. Potential switching risks (customers considering leaving for competitors)
4. Our competitive advantages mentioned by customers
5. Areas where we may be losing to competitors
6. Recommendations for the sales/product team

Use the actual company names and dates from the data."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "competitor_intelligence",
            "data": data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Competitor intelligence report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/compliance-risk")
async def api_compliance_risk_report(
    request: Request,
    max_score: int = 70,
    risk_level: str = None,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get compliance and risk report from Layer 5 data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        employee_filter = get_employee_filter(request)

        data = db.get_compliance_risk_data(
            max_score=max_score,
            risk_level=risk_level,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date,
            employee_filter=employee_filter
        )

        if data['total_issues'] == 0:
            return {
                "report": "compliance_risk",
                "response": f"No compliance issues found with score below {max_score}.",
                "data": data,
                "generated_at": datetime.now().isoformat()
            }

        # Build prompt
        issues_str = ""
        for issue in data['issues'][:12]:
            issues_str += f"""
- Date: {issue['call_date']}
  Agent: {issue['employee_name'] or 'Unknown'}
  Customer: {issue['customer_name'] or 'Unknown'} at {issue['customer_company'] or 'Unknown'}
  Compliance Score: {issue['compliance_score']}/100
  Risk Level: {issue['risk_level'].upper()}
  Summary: {(issue['summary'] or '')[:150]}...
"""

        agents_str = ""
        for agent in data['by_agent'][:8]:
            agents_str += f"\n- {agent['agent']}: {agent['total_calls']} calls, Avg Compliance: {agent['avg_compliance']}, Low Compliance: {agent['low_compliance_count']}"

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a Compliance & Risk Report based on the following ACTUAL DATA.

Today's date: {today}

## OVERVIEW:
- Total Compliance Issues: {data['total_issues']}
- Critical Risk (Score < 40): {data['critical_count']}
- High Risk (Score 40-60): {data['high_count']}
- Medium Risk (Score 60-70): {data['medium_count']}
- Average Compliance Score: {data['avg_compliance_score']}/100

## AGENTS WITH COMPLIANCE ISSUES:
{agents_str or "None identified"}

## COMPLIANCE ISSUE CALLS:
{issues_str}

Based on this data, provide:
1. Executive Summary of compliance health
2. Critical issues requiring immediate attention (with specific call details)
3. Agents who need compliance training
4. Common compliance failures detected
5. Risk mitigation recommendations
6. Suggested training topics

Use the actual agent names, dates, and scores from the data."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "compliance_risk",
            "data": data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Compliance risk report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/urgency-queue")
async def api_urgency_queue_report(
    request: Request,
    min_score: int = 7,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get urgency queue report from Layer 5 data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        employee_filter = get_employee_filter(request)

        data = db.get_urgency_queue_data(
            min_score=min_score,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date,
            employee_filter=employee_filter
        )

        if data['total_urgent'] == 0:
            return {
                "report": "urgency_queue",
                "response": f"No urgent calls found with score >= {min_score}.",
                "data": data,
                "generated_at": datetime.now().isoformat()
            }

        # Build prompt
        calls_str = ""
        for call in data['urgent_calls'][:15]:
            calls_str += f"""
- Date: {call['call_date']} {call['call_time'] or ''}
  Customer: {call['customer_name'] or 'Unknown'} at {call['customer_company'] or 'Unknown'}
  Agent: {call['employee_name'] or 'Unknown'}
  Urgency Score: {call['urgency_score']}/10
  Level: {call['urgency_level'].upper()}
  Resolution: {call['resolution_status'] or 'Unknown'}
  Follow-up Needed: {call['follow_up_needed']}
  Summary: {(call['summary'] or '')[:150]}...
"""

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate an Urgency Queue Report based on the following ACTUAL DATA.

Today's date: {today}

## OVERVIEW:
- Total Urgent Calls: {data['total_urgent']}
- Immediate Action Required (Score 9-10): {data['immediate_action']}
- High Priority (Score 7-8): {data['high_priority']}

## URGENCY DISTRIBUTION:
{data['by_urgency_level']}

## URGENT CALLS:
{calls_str}

Based on this data, provide:
1. Executive Summary of the urgency queue
2. Top 5 calls requiring IMMEDIATE action with specific next steps
3. Customers who may be at risk if not addressed quickly
4. Recommended prioritization for the support team
5. Patterns in urgent calls (time of day, type of issues)
6. Suggestions to reduce future urgent calls

Use the actual customer names, dates, and scores from the data."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "urgency_queue",
            "data": data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Urgency queue report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/key-quotes")
async def api_key_quotes_report(
    request: Request,
    search: str = None,
    quote_type: str = None,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get key quotes report from Layer 5 data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        employee_filter = get_employee_filter(request)

        data = db.get_key_quotes_data(
            search_term=search,
            quote_type=quote_type,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date,
            employee_filter=employee_filter
        )

        if data['total_quotes'] == 0:
            return {
                "report": "key_quotes",
                "response": "No key quotes found matching the criteria.",
                "data": data,
                "generated_at": datetime.now().isoformat()
            }

        # Build prompt
        quotes_str = ""
        for quote in data['quotes'][:20]:
            quotes_str += f"""
- "{quote['quote'][:200]}"
  Date: {quote['call_date']}
  Customer: {quote['customer_name'] or 'Unknown'} at {quote['customer_company'] or 'Unknown'}
  Sentiment: {quote['sentiment'] or 'Unknown'}
"""

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        search_context = f"Search term: '{search}'" if search else "All quotes"

        prompt = f"""Generate a Key Quotes Library Report based on the following ACTUAL DATA.

Today's date: {today}
Filter: {search_context}

## OVERVIEW:
- Total Quotes Found: {data['total_quotes']}

## KEY QUOTES:
{quotes_str}

Based on this data, provide:
1. Summary of themes in the quotes
2. Top 5 most impactful quotes for marketing/testimonials
3. Pain points customers are expressing (verbatim)
4. Feature requests or wishes mentioned
5. Positive feedback that could be used as testimonials
6. Suggested categories for organizing these quotes

Preserve the exact wording of quotes - they are verbatim from customers."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "key_quotes",
            "data": data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Key quotes report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/qa-training")
async def api_qa_training_report(
    request: Request,
    category: str = None,
    quality: str = None,
    faq_only: bool = False,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get Q&A training data report from Layer 5 data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        employee_filter = get_employee_filter(request)

        data = db.get_qa_training_data(
            category=category,
            quality=quality,
            faq_only=faq_only,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date,
            employee_filter=employee_filter
        )

        if data['total_qa_pairs'] == 0:
            return {
                "report": "qa_training",
                "response": "No Q&A pairs found matching the criteria.",
                "data": data,
                "generated_at": datetime.now().isoformat()
            }

        # Build prompt
        qa_str = ""
        for qa in data['qa_pairs'][:15]:
            qa_str += f"""
Q: {qa['question'][:200]}
A: {qa['answer'][:200]}
  Category: {qa['category']}
  Quality: {qa['answer_quality']}
  FAQ Candidate: {qa['could_be_faq']}
"""

        kb_str = "\n".join([f"- {a['article']} ({a['count']} mentions)" for a in data['potential_kb_articles'][:10]])
        cat_str = "\n".join([f"- {cat}: {count}" for cat, count in data['by_category'].items()])

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        prompt = f"""Generate a Q&A Training Data Report based on the following ACTUAL DATA.

Today's date: {today}

## OVERVIEW:
- Total Q&A Pairs: {data['total_qa_pairs']}
- FAQ Candidates: {data['faq_candidates']}
- Unanswered Questions: {data['unanswered']}

## BY CATEGORY:
{cat_str}

## POTENTIAL KB ARTICLES NEEDED:
{kb_str or "None identified"}

## SAMPLE Q&A PAIRS:
{qa_str}

Based on this data, provide:
1. Summary of common question types
2. Top 10 FAQ candidates that should be added to documentation
3. Questions that went unanswered (need KB articles)
4. Categories that need more documentation
5. Training recommendations for agents based on common questions
6. Suggested knowledge base improvements

Focus on actionable insights for improving documentation and training."""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "qa_training",
            "data": data,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Q&A training report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# HORMOZI SALES CALL ANALYZER
# ==========================================

HORMOZI_ANALYSIS_PROMPT = '''You are a sales coach trained on the Hormozi Sales Blueprint. Analyze this call transcript against these criteria:

## SPEED & RESPONSIVENESS CONTEXT
- Was this call made within 60 seconds of lead opt-in? (391% higher close rate)
- Was it same-day/next-day scheduling? (highest show rates)

## OPENING ANALYSIS (First 60 seconds)
Score each 1-10:
1. PROOF: Did rep establish credibility immediately?
2. PROMISE: Was the outcome/transformation stated?
3. PLAN: Was a clear agenda set?

Flag if: Rep asked "how can I help you?" (weak) vs. stated purpose confidently

## CLOSER FRAMEWORK BREAKDOWN

### CLARIFY (Why are they here?)
- Find the moment rep asked what prompted the call
- Did they tie it to a specific action? (clicked ad, scheduled, responded)
- Quote the exact question used

### LABEL (The Gap)
- Identify where rep summarized: "So you're at X, you want Y, and Z is blocking you"
- Was prospect confirmation obtained? (verbal yes)

### OVERVIEW PAST PAIN (The Pain Cycle)
This is where deals are won. Analyze:
- What solutions had prospect tried before?
- Did rep highlight what was MISSING from each attempt?
- Was cost of failure quantified? (time/money/status/daily cost)
- Time spent here: Target 40% of call

RED FLAG: If rep spent <5 minutes on pain, they rushed to pitch

### SELL THE VACATION (3-Pillar Pitch)
- Identify the 3 pillars presented
- Was each explained with a metaphor/analogy?
- Was pitch under 2 minutes? (it should be)
- Did rep talk about Maui, not the plane flight? (outcomes, not process)

### EXPLAIN CONCERNS (Objection Handling)
For each objection raised:
1. Classify: TIME | MONEY | DECISION-MAKER | STALL | DETAIL
2. Check AAA execution:
   - Acknowledge (repeated back/validated)
   - Associate (connected to success story or positive reframe)
   - Ask (followed with question, not statement)
3. Did rep ask: "What's your main concern?" before going into overcome?

DETAIL OBJECTIONS: Did rep fall into the death trap?
- Warning signs: Answering questions they didn't know prospect's preferred answer to
- Correct approach: "Which certifications were you looking for?" before answering

DECISION-MAKER OBJECTIONS: Check the 4-step process:
1. "What would happen if they said no?" (1/3 say "I'd do it anyway" = done)
2. "What do you think their main concern is?" (uncover real objection)
3. Past agreements (evidence partner would approve)
4. Support not permission (empowerment reframe)

### REINFORCE (Post-Close)
- Was there a warm handoff or cold hand-off?
- Did rep use BAMFAM (book a meeting from a meeting)?
- Were notes passed to next team member?

## TALK RATIO ANALYSIS
Calculate approximate:
- Prospect talk time: ___% (target: 66%)
- Rep talk time: ___% (target: 33%)

"The person asking questions is the person closing"

## QUESTION QUALITY AUDIT
List the questions rep asked. Score each:
- Open-ended exploration? (+1)
- Closed/leading? (0)
- Statement disguised as question? (-1)

## STATEMENTS VS QUESTIONS
Count how many times rep made a statement that could have been a question.
Statements = bombs that can blow up in your face

## SCRIPT ADHERENCE + DELIVERY
- Were core script elements present?
- EMPHASIS: Where did rep pause for impact?
- TONE: Did they go low for trust, high for questions?
- PACING: Slow for important points, fast for excitement?

## ZOMBIE CHECK (BANT)
Were these confirmed BEFORE asking for money?
- [ ] Budget: "What have you invested in solving this before?"
- [ ] Authority: "Is there anyone else involved in this decision?"
- [ ] Need: Established through pain cycle
- [ ] Timing: "When were you hoping to get started?"

## RED FLAGS CHECKLIST
- [ ] Asked prospect to repeat information from previous rep
- [ ] Got into details before establishing pain
- [ ] Answered price question without asking "compared to what?" or similar
- [ ] Negotiated on price (never negotiate with terrorists)
- [ ] Lost frame (prospect started asking all the questions)
- [ ] Commission breath detected (pushy, not curious)
- [ ] Talked past the close (prospect said yes, rep kept selling)

## QUOTABLE MOMENTS
Pull 3 quotes:
1. Strongest moment (for training)
2. Weakest moment (for coaching)
3. Missed opportunity (with better alternative)

## ONE-THING FOCUS
Based on this call, what ONE thing should this rep drill for the next 1-2 weeks?

## HOT STREAK CAPTURE
If this was a successful close, document:
- What made it work?
- What should be replicated?
- Which elements were slightly different from their usual?

## OVERALL SCORES
Provide scores out of 10 for each category:
- Opening (Proof/Promise/Plan): /10
- Pain Excavation: /10
- Pitch Delivery: /10
- Objection Handling: /10
- Close Execution: /10
- Overall Call Score: /10

---

## 🎯 HORMOZI COACHING PLAN

"The person who cares most about the prospect wins the sale." Based on this call, here's the coaching plan:

### THE ONE THING (Focus This Week)
Identify the SINGLE highest-impact improvement. Don't overwhelm with 28 corrections—ONE skill mastered beats 10 skills attempted.

**Priority Skill:** [Identify from: Clarify/Label/Pain Cycle/Vacation Sell/Objection Handling/Reinforce]
- Current Performance: X/10
- Target: X/10
- Why This First: [How this will impact close rate]

### CLOSER FRAMEWORK GAPS

For each phase where the rep fell short, provide specific coaching:

**C - Clarify:** Did they remind the prospect why they're on the call?
- Gap identified: [what was missing]
- Script to drill: "What made you take the time to hop on the call today?"
- Coach note: Never accept "I just want information" — dig for the real problem

**L - Label:** Did they establish the GAP clearly?
- Gap identified: [what was missing]
- Script to drill: "So just to make sure I'm clear—you want to get to X, you're currently at Y, and Z has been holding you back. Is that right?"

**O - Overview Pain:** Did they spend 40% of the call here? Did they quantify the cost of inaction?
- Gap identified: [what was missing]
- Questions to drill:
  - "What have you tried so far?"
  - "What did that cost you in time/money?"
  - "What is it costing you every month to NOT solve this?"
- Coach note: "The Pain is the Pitch" — if they rushed past pain, they have nothing to sell against

**S - Sell Vacation:** Did they paint the destination or describe the plane ride?
- Gap identified: [what was missing]
- Script to drill: "Imagine 90 days from now when [their specific goal]..."
- Coach note: Features = plane ride. Transformation = vacation. Sell the vacation.

**E - Explain Concerns:** How did they handle objections?
- Objection category faced: [TIME / MONEY / DECISION-MAKER / DETAILS / STALL]
- Did they use AAA? (Acknowledge → Associate → Ask)
- Gap identified: [what was missing]
- Better response to drill: "[specific rebuttal for this objection type]"

**R - Reinforce:** Did they set up a warm handoff?
- Gap identified: [what was missing]
- BAMFAM executed? (Book A Meeting From A Meeting)

### OBJECTION DRILL CARD

Based on objections faced in this call, create a drill card:

| Objection Heard | Category | Rep's Response | Better Response |
|-----------------|----------|----------------|-----------------|
| "[quote]" | [category] | [what they said] | "[Hormozi-style response]" |

**Rapid-Fire Questions to Memorize:**
When you get "I need to think about it":
- "What's your main concern?"
- "What are you afraid of having happen?"
- "What would make this a yes?"
- "What would make this a no?"

### SCRIPT MECHANICS FIXES

**Opening (Proof-Promise-Plan):** Did they nail the first 15-20 seconds?
- Issue: [what went wrong]
- Correct format: "We've helped [people like them] achieve [their goal]. Here's how this call will go—at the end we'll see if it makes sense. If not, no sweat."

**Tone & Delivery Notes:**
- Words to EMPHASIZE: [identify from transcript]
- Where to SLOW DOWN: [identify key moments]
- Where they lost FRAME: [identify if prospect took control]

### CONVICTION CHECK

"If a prospect knew everything you know about the product, they should buy."

**Conviction Gaps Detected:**
- [Did they sound uncertain? Quote the moment]
- [Did they apologize for price? Quote the moment]
- [Did "commission breath" show? Quote the moment]

**Conviction Rebuild Actions:**
1. Read 3 customer testimonials before next call
2. Record yourself when you're "hot" and analyze what's different
3. Remember: You're not selling—you're helping them justify a decision they already want to make

### MINDSET RESET

**Current Mindset Indicator:** [What they said/did that reveals their mental state]

**Hormozi Principle to Internalize:**
- [ ] "Be kind, not nice" — Kind people genuinely help even when uncomfortable
- [ ] "Objections do not mean no" — Unless they explicitly say NO, don't assume no
- [ ] "People want to buy" — They're only hesitant because they've been burned before
- [ ] "Volume negates luck" — Double the reps of the best closer on your team

**Affirmation:** "I'm here to genuinely help. I care more about this prospect than they care about themselves."

### ROLE-PLAY PRESCRIPTION

**Drill #1: [Specific CLOSER phase to practice]**
- Have coach play prospect
- Run the script 5-6 times in quick succession
- Focus on: [specific element - tone, pacing, emphasis]
- Success = rep can deliver without thinking

**Drill #2: Objection Gauntlet**
- Coach rapid-fires these objections:
  1. "[specific objection from this call]"
  2. "That's way too expensive"
  3. "I need to talk to my [spouse/partner/boss]"
  4. "Can you send me more information?"
- Rep must use AAA method for each
- Stack 2-3 closes per objection

### VOLUME PRESCRIPTION

"The relationship between volume and skill: The more you do, the better you get. The better you get, the more you do."

**This Week's Volume Target:**
- Calls to make: [current average × 1.5]
- Role-play sessions: [minimum 3]
- Testimonials to read: [daily]
- Script run-throughs: [5 per day]

### NEXT CALL CHECKLIST

Before the next call, rep must confirm:
- [ ] Script printed with tone markers (underline=slow, CAPS=emphasize)
- [ ] Pain cycle questions memorized
- [ ] Cost of inaction calculation ready
- [ ] Top 3 objection responses rehearsed
- [ ] "Pre-breathe ready" — nothing the prospect says will surprise me

### SUCCESS METRICS (Track Next 5 Calls)

| Metric | Target | Actual |
|--------|--------|--------|
| Time in Pain Cycle | 40%+ of call | ___ |
| Objections handled with AAA | 100% | ___ |
| BAMFAM executed | 100% | ___ |
| Script adherence | 100% first 2/3 | ___ |
| Asked "What would make this a yes?" | Every stall | ___ |

---

*"Closers ask hard questions because they genuinely care. If you come at it from 'I want the best thing for you,' you will always be on their side of the table."* — Alex Hormozi

Provide analysis with specific quotes from the transcript where possible.
'''


@app.get("/api/v1/rag/reports/sales-call-analysis")
async def api_sales_call_analysis(
    request: Request,
    recording_id: str = None,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None,
    employee: str = None
):
    """Analyze a sales call using the Hormozi Sales Blueprint methodology."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Build query to get call transcript
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if recording_id:
                    # Analyze specific call
                    cur.execute("""
                        SELECT
                            t.recording_id,
                            t.call_date,
                            t.call_time,
                            t.duration_seconds,
                            t.employee_name,
                            t.customer_name,
                            t.customer_company,
                            t.transcript_text,
                            i.customer_sentiment,
                            i.call_quality_score,
                            i.summary,
                            i.call_type
                        FROM transcripts t
                        LEFT JOIN insights i ON t.recording_id = i.recording_id
                        WHERE t.recording_id = %s
                    """, (recording_id,))
                    call = cur.fetchone()

                    if not call:
                        raise HTTPException(status_code=404, detail=f"Call {recording_id} not found")

                    calls = [dict(call)]
                else:
                    # Get recent calls for analysis selection
                    where_clauses = ["t.call_date IS NOT NULL", "t.transcript_text IS NOT NULL"]
                    params = []

                    if employee:
                        where_clauses.append("t.employee_name ILIKE %s")
                        params.append(f"%{employee}%")

                    if start_date and end_date:
                        where_clauses.append("t.call_date >= %s AND t.call_date <= %s")
                        params.extend([start_date, end_date])
                    elif date_range == 'last_30':
                        where_clauses.append("t.call_date >= CURRENT_DATE - INTERVAL '30 days'")
                    elif date_range == 'this_month':
                        where_clauses.append("t.call_date >= DATE_TRUNC('month', CURRENT_DATE)")

                    where_sql = " AND ".join(where_clauses)

                    cur.execute(f"""
                        SELECT
                            t.recording_id,
                            t.call_date,
                            t.call_time,
                            t.duration_seconds,
                            t.employee_name,
                            t.customer_name,
                            t.customer_company,
                            t.transcript_text,
                            i.customer_sentiment,
                            i.call_quality_score,
                            i.summary,
                            i.call_type
                        FROM transcripts t
                        LEFT JOIN insights i ON t.recording_id = i.recording_id
                        WHERE {where_sql}
                        AND LENGTH(t.transcript_text) > 500
                        ORDER BY t.call_date DESC
                        LIMIT 1
                    """, params)

                    call = cur.fetchone()
                    if not call:
                        return {
                            "report": "sales_call_analysis",
                            "response": "No calls found matching the criteria with sufficient transcript length.",
                            "generated_at": datetime.now().isoformat()
                        }
                    calls = [dict(call)]

        # Get the call to analyze
        call_data = calls[0]
        transcript = call_data.get('transcript_text', '')

        if not transcript or len(transcript) < 100:
            return {
                "report": "sales_call_analysis",
                "response": "Transcript too short for meaningful analysis.",
                "call": {
                    "recording_id": call_data.get('recording_id'),
                    "employee": call_data.get('employee_name'),
                    "date": str(call_data.get('call_date'))
                },
                "generated_at": datetime.now().isoformat()
            }

        # Prepare context for analysis
        call_context = f"""
## CALL METADATA
- Recording ID: {call_data.get('recording_id')}
- Date: {call_data.get('call_date')} {call_data.get('call_time', '')}
- Duration: {call_data.get('duration_seconds', 0)} seconds ({round((call_data.get('duration_seconds', 0) or 0) / 60, 1)} minutes)
- Agent/Rep: {call_data.get('employee_name', 'Unknown')}
- Customer: {call_data.get('customer_name', 'Unknown')}
- Company: {call_data.get('customer_company', 'Unknown')}
- Call Type: {call_data.get('call_type', 'Unknown')}
- Sentiment: {call_data.get('customer_sentiment', 'Unknown')}
- Quality Score: {call_data.get('call_quality_score', 'N/A')}/10

## TRANSCRIPT
{transcript[:15000]}
"""

        # Use Gemini to analyze
        from google import genai
        from google.genai import types

        config = get_config_instance()
        client = genai.Client(api_key=config.gemini_api_key)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{HORMOZI_ANALYSIS_PROMPT}\n\n{call_context}",
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096
            )
        )

        analysis = response.text

        return {
            "report": "sales_call_analysis",
            "methodology": "Hormozi Sales Blueprint",
            "call": {
                "recording_id": call_data.get('recording_id'),
                "date": str(call_data.get('call_date')),
                "time": str(call_data.get('call_time', '')),
                "duration_minutes": round((call_data.get('duration_seconds', 0) or 0) / 60, 1),
                "employee": call_data.get('employee_name'),
                "customer": call_data.get('customer_name'),
                "company": call_data.get('customer_company'),
                "call_type": call_data.get('call_type'),
                "sentiment": call_data.get('customer_sentiment'),
                "quality_score": call_data.get('call_quality_score')
            },
            "analysis": analysis,
            "generated_at": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sales call analysis error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/sales-calls-list")
async def api_sales_calls_list(
    request: Request,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None,
    employee: str = None,
    limit: int = 20
):
    """Get list of calls available for sales analysis."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where_clauses = [
                    "t.call_date IS NOT NULL",
                    "t.transcript_text IS NOT NULL",
                    "LENGTH(t.transcript_text) > 500"
                ]
                params = []

                if employee:
                    # Get all name variations for this employee
                    variations = get_employee_name_variations(employee)
                    if variations:
                        # Build OR clause for all variations
                        variation_clauses = []
                        for var in variations:
                            variation_clauses.append("t.employee_name ILIKE %s")
                            params.append(f"%{var}%")
                        where_clauses.append(f"({' OR '.join(variation_clauses)})")

                if start_date and end_date:
                    where_clauses.append("t.call_date >= %s AND t.call_date <= %s")
                    params.extend([start_date, end_date])
                elif date_range == 'last_30':
                    where_clauses.append("t.call_date >= CURRENT_DATE - INTERVAL '30 days'")
                elif date_range == 'this_month':
                    where_clauses.append("t.call_date >= DATE_TRUNC('month', CURRENT_DATE)")
                elif date_range == 'this_quarter':
                    where_clauses.append("t.call_date >= DATE_TRUNC('quarter', CURRENT_DATE)")

                where_sql = " AND ".join(where_clauses)
                params.append(limit)

                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.call_time,
                        t.duration_seconds,
                        t.employee_name,
                        t.customer_name,
                        t.customer_company,
                        LENGTH(t.transcript_text) as transcript_length,
                        i.customer_sentiment,
                        i.call_quality_score,
                        i.call_type,
                        i.summary
                    FROM transcripts t
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    WHERE {where_sql}
                    ORDER BY t.call_date DESC, t.call_time DESC
                    LIMIT %s
                """, params)

                calls = []
                for row in cur.fetchall():
                    call = dict(row)
                    call['call_date'] = str(call['call_date']) if call['call_date'] else None
                    call['call_time'] = str(call['call_time']) if call['call_time'] else None
                    call['duration_minutes'] = round((call.get('duration_seconds', 0) or 0) / 60, 1)
                    calls.append(call)

                return {
                    "calls": calls,
                    "count": len(calls),
                    "filters": {
                        "date_range": date_range,
                        "employee": employee
                    }
                }

    except Exception as e:
        logger.error(f"Sales calls list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# EMAIL REPORT ENDPOINTS
# ==========================================

@app.get("/api/v1/email/recipients")
async def api_email_recipients(request: Request):
    """Get list of users for email recipient dropdown."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT username, email, role
                    FROM users
                    WHERE is_active = true AND email IS NOT NULL
                    ORDER BY username
                """)
                users = [dict(row) for row in cur.fetchall()]

                return {
                    "recipients": users,
                    "count": len(users)
                }

    except Exception as e:
        logger.error(f"Email recipients error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/email/send-report")
async def api_send_report_email(request: Request, email_request: EmailReportRequest):
    """Send a report via email."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_current_user(request)
        sender_name = user.get('username', 'Unknown') if user else 'Unknown'

        # Generate clean subject line (avoid spam triggers)
        report_type_labels = {
            "sales-pipeline": "Sales Pipeline Report",
            "competitor-intelligence": "Competitor Analysis",
            "compliance-risk": "Compliance Review",
            "urgency-queue": "Priority Items",
            "key-quotes": "Customer Quotes Summary",
            "qa-training": "Training Data Summary",
            "sales-call-analysis": "Call Analysis",
            "churn": "Customer Risk Report",
            "agent": "Performance Report",
            "sentiment": "Customer Feedback Summary",
            "quality": "Quality Review"
        }

        report_label = report_type_labels.get(email_request.report_type, "Report")

        # Clean subject - no brackets, no ALL CAPS, conversational
        subject = f"{report_label} from {sender_name}"

        # Add sender info to body
        body = f"Shared by: {sender_name}\n"
        body += f"Report: {email_request.report_title}\n"
        body += "-" * 50 + "\n\n"
        body += email_request.report_content

        result = send_email(
            to_email=email_request.recipient_email,
            subject=subject,
            body=body
        )

        logger.info(f"Report emailed to {email_request.recipient_email} by {sender_name}")

        return {
            "success": True,
            "message": f"Report sent to {email_request.recipient_email}",
            "subject": subject
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=500, detail="Email authentication failed - check SMTP credentials")
    except Exception as e:
        logger.error(f"Send report email error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# INTERACTIVE HORMOZI COACHING API
# ============================================================================

HORMOZI_COACHING_PROMPT = '''You are an expert sales coach trained in Alex Hormozi's sales methodology.

Your coaching philosophy:
- "The person who cares most about the prospect wins the sale"
- "Volume negates luck" - push for massive repetition
- "Sales is an education process over a bridge of trust"
- "Be kind, not nice" - genuinely help even when uncomfortable
- "Don't be cute" - do the fundamentals flawlessly every time

CLOSER Framework:
- C: Clarify why they're here (connect action to problem)
- L: Label the gap (current state → desired state → obstacle)
- O: Overview past pain (40% of call, quantify cost of inaction)
- S: Sell the vacation (outcomes, not features)
- E: Explain concerns (AAA: Acknowledge, Associate, Ask)
- R: Reinforce the decision (warm handoff, BAMFAM)

When coaching, you will:
1. Evaluate the sales rep's response against Hormozi principles
2. Provide specific, actionable feedback with scores (1-10)
3. Quote what they said and suggest improvements
4. Continue the role-play as the prospect
5. Be direct but encouraging - "kind, not nice"
'''

class CoachingRequest(BaseModel):
    mode: str
    user_response: str
    history: list = []
    call_context: dict = None
    analysis_context: str = None

class IdealResponseRequest(BaseModel):
    mode: str
    prospect_message: str


@app.post("/api/v1/coaching/respond")
async def coaching_respond(request: Request, coaching_req: CoachingRequest):
    """Interactive coaching - evaluate response and continue role-play."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        from google import genai
        from google.genai import types

        config = get_config_instance()
        client = genai.Client(api_key=config.gemini_api_key)

        # Build conversation history
        history_text = ""
        for msg in coaching_req.history[-6:]:  # Last 6 messages for context
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            history_text += f"{role.upper()}: {content}\n\n"

        # Mode-specific coaching focus
        mode_focus = {
            'roleplay': "Evaluate their overall sales conversation skills. Focus on whether they're following the CLOSER framework.",
            'objection': "Focus on their objection handling. Did they use AAA (Acknowledge, Associate, Ask)? Did they avoid 'death trap' details?",
            'pain': "Focus on pain excavation. Did they dig deep? Did they quantify cost of inaction? Did they ask about past solutions?",
            'opening': "Focus on their opening. Did they use Proof-Promise-Plan in 15-20 seconds? Did they set a clear agenda?",
            'close': "Focus on close execution. Did they confirm BANT first? Did they use stacked closes? Did they avoid talking past the close?"
        }

        coaching_focus = mode_focus.get(coaching_req.mode, mode_focus['roleplay'])

        prompt = f"""{HORMOZI_COACHING_PROMPT}

COACHING MODE: {coaching_req.mode}
FOCUS: {coaching_focus}

CONVERSATION SO FAR:
{history_text}

SALES REP'S LATEST RESPONSE:
"{coaching_req.user_response}"

Please provide:
1. **SCORE (1-10):** Rate this response against Hormozi principles
2. **FEEDBACK:** 2-3 sentences on what they did well and what to improve. Be specific - quote their words.
3. **HORMOZI TIP:** One specific technique from the framework they should apply
4. **NEXT_PROMPT:** Continue as the prospect - respond naturally to what they said, creating a realistic conversation flow.

Format your response as JSON:
{{
    "score": 7,
    "feedback": "Your feedback here...",
    "hormozi_tip": "Remember: [specific tip]",
    "next_prompt": "Prospect's next response..."
}}
"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=1024
            )
        )

        # Parse JSON response
        text = response.text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
        if text.endswith('```'):
            text = text.rsplit('\n', 1)[0]

        import json
        try:
            data = json.loads(text)
        except:
            # Fallback if JSON parsing fails
            data = {
                "score": 5,
                "feedback": text[:500],
                "hormozi_tip": "Remember the CLOSER framework.",
                "next_prompt": "Interesting. Tell me more about that."
            }

        # Format feedback message
        feedback = f"**Score: {data.get('score', 5)}/10**\n\n"
        feedback += data.get('feedback', '') + "\n\n"
        feedback += f"💡 *{data.get('hormozi_tip', '')}*"

        return {
            "feedback": feedback,
            "score": data.get('score', 5),
            "next_prompt": data.get('next_prompt', 'Tell me more about that.')
        }

    except Exception as e:
        logger.error(f"Coaching respond error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/coaching/ideal-response")
async def coaching_ideal_response(request: Request, req: IdealResponseRequest):
    """Generate the ideal Hormozi-style response for a prospect message."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        from google import genai
        from google.genai import types

        config = get_config_instance()
        client = genai.Client(api_key=config.gemini_api_key)

        mode_context = {
            'roleplay': "a full sales conversation",
            'objection': "handling objections with AAA method",
            'pain': "excavating pain and quantifying cost of inaction",
            'opening': "the Proof-Promise-Plan opening",
            'close': "closing with BANT confirmation and stacked closes"
        }

        prompt = f"""{HORMOZI_COACHING_PROMPT}

The prospect just said: "{req.prospect_message}"

This is a practice scenario for {mode_context.get(req.mode, 'sales')}.

Provide the IDEAL Hormozi-style response a top closer would give.

Format as JSON:
{{
    "ideal_response": "The exact words the rep should say...",
    "explanation": "Why this response works according to Hormozi principles (2-3 sentences)"
}}
"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=512
            )
        )

        text = response.text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
        if text.endswith('```'):
            text = text.rsplit('\n', 1)[0]

        import json
        try:
            data = json.loads(text)
        except:
            data = {
                "ideal_response": text[:300],
                "explanation": "This response follows Hormozi's framework."
            }

        return data

    except Exception as e:
        logger.error(f"Ideal response error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# USER ACTIVITY DASHBOARD
# ============================================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """User dashboard - shows the logged-in user's own metrics."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(request)

    return templates.TemplateResponse("dashboard_user.html", {
        "request": request,
        "user": user,
        "employee_name": user.get('employee_name') or user.get('display_name'),
        "is_admin": user.get('role') == 'admin',
        "page_title": "My Dashboard"
    })


@app.get("/dashboard/admin", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request):
    """Admin dashboard - shows all users' metrics."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    user = get_current_user(request)
    employees = get_canonical_employee_list()

    return templates.TemplateResponse("dashboard_admin.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "page_title": "Team Dashboard"
    })


@app.get("/dashboard/admin/user/{employee_name}", response_class=HTMLResponse)
async def admin_user_detail_page(request: Request, employee_name: str):
    """Admin view of a specific user's dashboard."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    user = get_current_user(request)

    return templates.TemplateResponse("dashboard_user.html", {
        "request": request,
        "user": user,
        "employee_name": employee_name,
        "is_admin": True,
        "is_admin_view": True,
        "page_title": f"Dashboard - {employee_name}"
    })


@app.get("/api/v1/dashboard/metrics")
async def api_dashboard_metrics(
    request: Request,
    employee: Optional[str] = None,
    period: str = "today",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Get dashboard metrics for an employee.

    Query Parameters:
        employee: Employee name (optional, defaults to current user for non-admins)
        period: today, wtd, last_week, mtd, qtd, ytd, custom
        start_date: For custom period (YYYY-MM-DD)
        end_date: For custom period (YYYY-MM-DD)
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = get_current_user(request)
    is_user_admin = user.get('role') == 'admin'

    # Determine which employee to get metrics for
    if employee:
        # Non-admins can only view their own data
        if not is_user_admin:
            user_employee = user.get('employee_name') or user.get('display_name')
            if employee.lower() != user_employee.lower():
                raise HTTPException(status_code=403, detail="Access denied")
        target_employee = employee
    else:
        # Default to current user's data
        target_employee = user.get('employee_name') or user.get('display_name')

    if not target_employee:
        raise HTTPException(status_code=400, detail="Employee name not found")

    try:
        service = get_metrics_service()
        metrics = service.get_combined_metrics(
            employee_name=target_employee,
            period=period,
            start_date=start_date,
            end_date=end_date
        )

        return {
            "success": True,
            "data": metrics,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Dashboard metrics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/dashboard/admin/team")
async def api_admin_team_metrics(
    request: Request,
    period: str = "today",
    min_activity: int = 1
):
    """
    Get metrics for all active team members (admin only).

    Query Parameters:
        period: today, wtd, last_week, mtd, qtd, ytd
        min_activity: Minimum calls OR tickets to be included (default: 1)
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        service = get_metrics_service()
        team_metrics = service.get_team_metrics(period=period, min_activity=min_activity)

        # Calculate team totals
        team_totals = {
            'total_employees': len(team_metrics),
            'total_calls': sum(m['calls']['total_calls'] for m in team_metrics),
            'total_answered': sum(m['calls']['answered_calls'] for m in team_metrics),
            'avg_answer_rate': 0,
            'avg_quality_score': 0,
            'total_tickets_closed': sum(m['tickets']['tickets_closed'] for m in team_metrics),
            'total_overdue': sum(m['tickets']['tickets_over_5_days'] for m in team_metrics),
            'avg_productivity_score': 0
        }

        if team_totals['total_calls'] > 0:
            team_totals['avg_answer_rate'] = round(
                team_totals['total_answered'] / team_totals['total_calls'] * 100, 1
            )

        if team_metrics:
            team_totals['avg_productivity_score'] = round(
                sum(m['productivity']['score'] for m in team_metrics) / len(team_metrics), 1
            )
            # Calculate avg quality score
            quality_scores = [m['quality']['avg_quality_score'] for m in team_metrics
                            if m['quality']['avg_quality_score'] is not None]
            if quality_scores:
                team_totals['avg_quality_score'] = round(sum(quality_scores) / len(quality_scores), 1)

        return {
            "success": True,
            "period": period,
            "team_totals": team_totals,
            "employees": team_metrics,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Admin team metrics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/dashboard/admin/export")
async def api_export_team_metrics(
    request: Request,
    period: str = "today",
    format: str = "csv"
):
    """Export team metrics as CSV (admin only)."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        service = get_metrics_service()
        team_metrics = service.get_team_metrics(period=period)

        # Generate CSV
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'Employee', 'Total Calls', 'Answered', 'Missed', 'Answer Rate %',
            'Avg Duration (s)', 'Inbound', 'Outbound',
            'Tickets Opened', 'Tickets Closed', 'Open Total', 'Overdue (>5d)',
            'Avg Quality', 'Escalations', 'Productivity Score', 'Grade'
        ])

        # Data rows
        for m in team_metrics:
            writer.writerow([
                m['employee_name'],
                m['calls']['total_calls'],
                m['calls']['answered_calls'],
                m['calls']['missed_calls'],
                m['calls']['answer_rate'],
                round(m['calls']['avg_duration_seconds'], 1),
                m['calls']['inbound_calls'],
                m['calls']['outbound_calls'],
                m['tickets']['tickets_opened'],
                m['tickets']['tickets_closed'],
                m['tickets']['tickets_open_total'],
                m['tickets']['tickets_over_5_days'],
                m['quality']['avg_quality_score'],
                m['quality']['escalation_count'],
                m['productivity']['score'],
                m['productivity']['grade']
            ])

        csv_content = output.getvalue()

        from fastapi.responses import Response
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=team_metrics_{period}_{datetime.now().strftime('%Y%m%d')}.csv"
            }
        )

    except Exception as e:
        logger.error(f"Export team metrics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/dashboard/periods")
async def api_dashboard_periods(request: Request):
    """Get available period options for dashboard."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    from datetime import date, timedelta
    today = date.today()

    return {
        "periods": [
            {"value": "today", "label": "Today", "start": today.isoformat(), "end": today.isoformat()},
            {"value": "wtd", "label": "Week to Date",
             "start": (today - timedelta(days=today.weekday())).isoformat(), "end": today.isoformat()},
            {"value": "last_week", "label": "Last Week",
             "start": (today - timedelta(days=today.weekday() + 7)).isoformat(),
             "end": (today - timedelta(days=today.weekday() + 1)).isoformat()},
            {"value": "mtd", "label": "Month to Date",
             "start": date(today.year, today.month, 1).isoformat(), "end": today.isoformat()},
            {"value": "qtd", "label": "Quarter to Date",
             "start": date(today.year, ((today.month - 1) // 3) * 3 + 1, 1).isoformat(), "end": today.isoformat()},
            {"value": "ytd", "label": "Year to Date",
             "start": date(today.year, 1, 1).isoformat(), "end": today.isoformat()},
            {"value": "custom", "label": "Custom Range", "start": None, "end": None}
        ]
    }


# ============================================================================
# ADMIN: FRESHDESK AGENT MAPPING
# ============================================================================

@app.get("/admin/agent-mapping", response_class=HTMLResponse)
async def admin_agent_mapping_page(request: Request):
    """Admin page to manage Freshdesk agent to PCR employee mappings."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    user = get_current_user(request)
    employees = get_canonical_employee_list()

    return templates.TemplateResponse("admin_agent_mapping.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "page_title": "Agent Mapping"
    })


@app.get("/api/v1/admin/agent-mappings")
async def api_get_agent_mappings(request: Request):
    """Get all Freshdesk agent mappings."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    import psycopg2
    db_url = os.getenv(
        'RAG_DATABASE_URL',
        os.getenv('DATABASE_URL', '')
    )

    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    id,
                    freshdesk_agent_name,
                    pcr_employee_name,
                    ticket_count,
                    first_seen_at,
                    last_seen_at,
                    mapped_by,
                    mapped_at,
                    auto_matched
                FROM freshdesk_agent_map
                ORDER BY ticket_count DESC
            """)
            mappings = [dict(row) for row in cur.fetchall()]

        conn.close()

        # Convert datetimes to strings
        for m in mappings:
            for key in ['first_seen_at', 'last_seen_at', 'mapped_at']:
                if m.get(key):
                    m[key] = m[key].isoformat()

        return {
            "success": True,
            "mappings": mappings,
            "total": len(mappings),
            "unmapped_count": sum(1 for m in mappings if not m['pcr_employee_name'])
        }

    except Exception as e:
        logger.error(f"Get agent mappings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/admin/agent-mappings/{agent_id}")
async def api_update_agent_mapping(
    request: Request,
    agent_id: int,
    pcr_employee: Optional[str] = Form(None)
):
    """Update a Freshdesk agent mapping."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    user = get_current_user(request)
    import psycopg2
    db_url = os.getenv(
        'RAG_DATABASE_URL',
        os.getenv('DATABASE_URL', '')
    )

    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE freshdesk_agent_map
                SET pcr_employee_name = %s,
                    mapped_by = %s,
                    mapped_at = NOW(),
                    auto_matched = FALSE,
                    updated_at = NOW()
                WHERE id = %s
            """, (pcr_employee if pcr_employee else None,
                  user.get('username'),
                  agent_id))
            conn.commit()

        conn.close()

        return {
            "success": True,
            "message": f"Mapping updated for agent ID {agent_id}"
        }

    except Exception as e:
        logger.error(f"Update agent mapping error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================
# Email Trigger Management Routes
# =========================================

from rag_integration.services.dashboard_triggers import get_trigger_service


@app.get("/admin/triggers", response_class=HTMLResponse)
async def admin_triggers_page(request: Request):
    """Admin page to manage email triggers."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    user = get_current_user(request)
    employees = get_canonical_employee_list()

    return templates.TemplateResponse("admin_triggers.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "page_title": "Email Triggers"
    })


@app.get("/api/v1/triggers")
async def api_list_triggers(
    request: Request,
    active_only: bool = False
):
    """List all email triggers."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        service = get_trigger_service()
        triggers = service.list_triggers(active_only=active_only)

        # Convert datetime objects to strings for JSON serialization
        for t in triggers:
            for key in ['created_at', 'updated_at', 'last_triggered_at', 'schedule_time']:
                if t.get(key) and hasattr(t[key], 'isoformat'):
                    t[key] = t[key].isoformat()

        return {"success": True, "data": triggers}

    except Exception as e:
        logger.error(f"List triggers error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/triggers")
async def api_create_trigger(request: Request):
    """Create a new email trigger."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        body = await request.json()
        user = get_current_user(request)

        service = get_trigger_service()
        trigger_id = service.create_trigger(body, created_by=user.get('username'))

        return {
            "success": True,
            "trigger_id": trigger_id,
            "message": "Trigger created successfully"
        }

    except Exception as e:
        logger.error(f"Create trigger error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/triggers/{trigger_id}")
async def api_get_trigger(request: Request, trigger_id: int):
    """Get a specific trigger."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        service = get_trigger_service()
        trigger = service.get_trigger(trigger_id)

        if not trigger:
            raise HTTPException(status_code=404, detail="Trigger not found")

        # Convert datetime objects
        for key in ['created_at', 'updated_at', 'last_triggered_at', 'schedule_time']:
            if trigger.get(key) and hasattr(trigger[key], 'isoformat'):
                trigger[key] = trigger[key].isoformat()

        return {"success": True, "data": trigger}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get trigger error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/triggers/{trigger_id}")
async def api_update_trigger(request: Request, trigger_id: int):
    """Update an existing trigger."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        body = await request.json()
        service = get_trigger_service()
        success = service.update_trigger(trigger_id, body)

        if not success:
            raise HTTPException(status_code=404, detail="Trigger not found or no changes made")

        return {"success": True, "message": "Trigger updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update trigger error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/triggers/{trigger_id}")
async def api_delete_trigger(request: Request, trigger_id: int):
    """Delete a trigger."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        service = get_trigger_service()
        success = service.delete_trigger(trigger_id)

        if not success:
            raise HTTPException(status_code=404, detail="Trigger not found")

        return {"success": True, "message": "Trigger deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete trigger error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/triggers/{trigger_id}/test")
async def api_test_trigger(
    request: Request,
    trigger_id: int,
    employee: Optional[str] = None
):
    """
    Test a trigger without sending email.
    Returns what would happen if the trigger was evaluated.
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        trigger_service = get_trigger_service()
        metrics_service = get_metrics_service()

        trigger = trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail="Trigger not found")

        # Get employees to test
        if employee:
            employees = [employee]
        elif trigger.get('applies_to') == 'specific_users' and trigger.get('target_employees'):
            employees = trigger['target_employees']
        else:
            # Get first 5 active employees for testing
            team = metrics_service.get_team_metrics(period='today')
            employees = [m['employee_name'] for m in team[:5]]

        results = []
        for emp in employees:
            metrics = metrics_service.get_combined_metrics(emp, 'today')
            evaluation = trigger_service.evaluate_trigger(trigger, emp, metrics)
            recipients = trigger_service._get_recipients(trigger, emp)

            results.append({
                'employee': emp,
                'would_fire': evaluation['should_fire'],
                'reason': evaluation.get('reason', ''),
                'recipients': recipients,
                'metrics_summary': {
                    'answer_rate': metrics.get('calls', {}).get('answer_rate', 0),
                    'quality_score': metrics.get('quality', {}).get('avg_quality_score', 0),
                    'productivity_score': metrics.get('productivity', {}).get('score', 0)
                }
            })

        return {
            "success": True,
            "trigger_name": trigger.get('name'),
            "test_results": results,
            "message": f"Tested against {len(employees)} employees"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test trigger error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/triggers/history")
async def api_trigger_history(
    request: Request,
    trigger_id: Optional[int] = None,
    employee: Optional[str] = None,
    limit: int = 50
):
    """Get trigger execution history."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        service = get_trigger_service()
        history = service.get_trigger_history(
            trigger_id=trigger_id,
            employee_name=employee,
            limit=limit
        )

        # Convert datetime objects
        for h in history:
            if h.get('triggered_at') and hasattr(h['triggered_at'], 'isoformat'):
                h['triggered_at'] = h['triggered_at'].isoformat()

        return {"success": True, "data": history}

    except Exception as e:
        logger.error(f"Get trigger history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# VIDEO MEETING INTELLIGENCE API
# ============================================================================

@app.get("/learning", response_class=HTMLResponse)
async def learning_module_page(request: Request):
    """Learning module dashboard page with coaching data."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        db = get_db()
        # Original learning stats
        stats = db.get_learning_module_stats()
        recent_sessions = db.get_video_meetings(limit=15)
        attention_needed = db.get_learning_attention_needed(limit=10)

        # New coaching data - combines calls + video meetings
        coaching_stats = db.get_coaching_summary_stats()
        coaching_feed = db.get_coaching_feed(limit=30)
        coaching_queue = db.get_coaching_queue(limit=15)

        return templates.TemplateResponse("learning_module.html", {
            "request": request,
            "stats": stats,
            "recent_sessions": recent_sessions.get('meetings', []),
            "attention_needed": attention_needed,
            # Coaching additions
            "coaching_stats": coaching_stats,
            "coaching_feed": coaching_feed,
            "coaching_queue": coaching_queue
        })
    except Exception as e:
        logger.error(f"Learning module page error: {e}")
        return templates.TemplateResponse("learning_module.html", {
            "request": request,
            "stats": {},
            "recent_sessions": [],
            "attention_needed": [],
            "coaching_stats": {},
            "coaching_feed": [],
            "coaching_queue": [],
            "error": str(e)
        })


@app.get("/video-meetings", response_class=HTMLResponse)
async def video_meetings_page(request: Request):
    """Video meetings dashboard page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        db = get_db()
        stats = db.get_video_meeting_stats()
        meetings = db.get_video_meetings(limit=20)

        return templates.TemplateResponse("video_meetings.html", {
            "request": request,
            "stats": stats,
            "meetings": meetings['meetings'],
            "total": meetings['total']
        })
    except Exception as e:
        logger.error(f"Video meetings page error: {e}")
        return templates.TemplateResponse("video_meetings.html", {
            "request": request,
            "stats": {},
            "meetings": [],
            "total": 0,
            "error": str(e)
        })


@app.get("/video-meetings/{meeting_id}", response_class=HTMLResponse)
async def video_meeting_detail_page(request: Request, meeting_id: int):
    """Video meeting detail page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        db = get_db()
        meeting = db.get_video_meeting_detail(meeting_id)

        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        return templates.TemplateResponse("video_meeting_detail.html", {
            "request": request,
            "meeting": meeting
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video meeting detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/video-meetings")
async def api_video_meetings(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    meeting_type: str = None,
    trainer: str = None,
    sentiment: str = None,
    learning_state: str = None,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get video meetings with filters."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        result = db.get_video_meetings(
            limit=limit,
            offset=offset,
            meeting_type=meeting_type,
            trainer=trainer,
            sentiment=sentiment,
            learning_state=learning_state,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date
        )

        # Convert datetime objects
        for m in result['meetings']:
            if m.get('start_time') and hasattr(m['start_time'], 'isoformat'):
                m['start_time'] = m['start_time'].isoformat()

        return {"success": True, "data": result}

    except Exception as e:
        logger.error(f"Video meetings API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/video-meetings/stats")
async def api_video_meeting_stats(request: Request):
    """Get video meeting statistics."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        stats = db.get_video_meeting_stats()
        return {"success": True, "data": stats}

    except Exception as e:
        logger.error(f"Video meeting stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/video-meetings/{meeting_id}")
async def api_video_meeting_detail(request: Request, meeting_id: int):
    """Get video meeting details."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        meeting = db.get_video_meeting_detail(meeting_id)

        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        # Convert datetime objects
        for key in ['start_time', 'end_time', 'created_at', 'updated_at']:
            if meeting.get(key) and hasattr(meeting[key], 'isoformat'):
                meeting[key] = meeting[key].isoformat()

        return {"success": True, "data": meeting}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video meeting detail API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/training-effectiveness")
async def api_training_report(
    request: Request,
    trainer: str = None,
    date_range: str = None,
    start_date: str = None,
    end_date: str = None
):
    """Get training effectiveness report from video meetings."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        report = db.get_video_training_report(
            trainer=trainer,
            date_range=date_range,
            start_date=start_date,
            end_date=end_date
        )

        # Generate summary
        if report['total_sessions'] > 0:
            avg_learning = report.get('avg_learning_score') or 0
            learning_grade = 'A' if avg_learning >= 8 else 'B' if avg_learning >= 7 else 'C' if avg_learning >= 6 else 'D'

            summary = f"""## Training Effectiveness Report

**Sessions Analyzed:** {report['total_sessions']}
**Average Learning Score:** {avg_learning:.1f}/10 (Grade: {learning_grade})
**Average Quality:** {(report.get('avg_quality') or 0):.1f}/10
**Average Satisfaction:** {(report.get('avg_satisfaction') or 0):.1f}/10

### Learning Outcomes
- **Aha Moments:** {report.get('aha_moments', 0)} sessions
- **Struggling:** {report.get('struggling', 0)} sessions
- **High Churn Risk:** {report.get('high_risk', 0)} sessions
"""
            if report.get('attention_needed'):
                summary += "\n### Sessions Needing Attention\n"
                for s in report['attention_needed'][:5]:
                    summary += f"- [{s['title'][:40]}...](/video-meetings/{s['id']}) - {s['learning_state']}\n"
        else:
            summary = "No training sessions found matching the criteria."

        return {
            "report": "training_effectiveness",
            "response": summary,
            "data": report,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Training report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COACHING & LEARNING API
# ============================================================================

@app.get("/api/v1/coaching/feed")
async def api_coaching_feed(
    request: Request,
    employee: str = None,
    limit: int = 50,
    include_calls: bool = True,
    include_video: bool = True
):
    """Get coaching feed with combined call and video meeting coaching data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        feed = db.get_coaching_feed(
            employee_name=employee,
            limit=limit,
            include_calls=include_calls,
            include_video=include_video
        )
        return {"success": True, "data": feed, "count": len(feed)}

    except Exception as e:
        logger.error(f"Coaching feed API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/coaching/employee/{employee_name}")
async def api_employee_coaching(
    request: Request,
    employee_name: str,
    period: str = "mtd"
):
    """Get coaching progress for a specific employee."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        progress = db.get_employee_coaching_progress(employee_name, period)
        coaching_feed = db.get_coaching_feed(employee_name=employee_name, limit=20)

        return {
            "success": True,
            "progress": progress,
            "recent_coaching": coaching_feed
        }

    except Exception as e:
        logger.error(f"Employee coaching API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/coaching/queue")
async def api_coaching_queue(request: Request, limit: int = 20):
    """Get interactions needing coaching attention."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        queue = db.get_coaching_queue(limit=limit)
        return {"success": True, "data": queue, "count": len(queue)}

    except Exception as e:
        logger.error(f"Coaching queue API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/coaching/stats")
async def api_coaching_stats(request: Request):
    """Get overall coaching statistics."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()
        stats = db.get_coaching_summary_stats()
        return {"success": True, "data": stats}

    except Exception as e:
        logger.error(f"Coaching stats API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def create_app():
    """Factory function for creating the app."""
    return app


if __name__ == "__main__":
    config = get_config_instance()
    uvicorn.run(
        "rag_integration.api.main:app",
        host="0.0.0.0",
        port=config.api_port,
        reload=True
    )
