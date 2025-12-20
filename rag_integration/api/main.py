"""RAG Integration FastAPI Application"""

import os
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any
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
import uvicorn

from rag_integration.config.settings import get_config
from rag_integration.services.db_reader import DatabaseReader
from rag_integration.services.gemini_file_search import GeminiFileSearchService
from rag_integration.services.vertex_rag import VertexRAGService
from rag_integration.services.query_router import UnifiedQueryService, QueryRouter
from rag_integration.jobs.export_pipeline import ExportPipeline

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="COWS RAG API",
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
def check_auth(request: Request) -> bool:
    """Check if user is authenticated."""
    return request.session.get("authenticated", False)


def require_auth(request: Request):
    """Require authentication dependency."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return True


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
async def login(request: Request, password: str = Form(...)):
    """Process login."""
    config = get_config_instance()
    if password == config.api_password:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})


@app.get("/logout")
async def logout(request: Request):
    """Logout."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


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
        "result": None
    })


@app.post("/query", response_class=HTMLResponse)
async def query_submit(request: Request, query: str = Form(...), system: str = Form("auto")):
    """Process query from web form."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        service = get_query_service()
        force_system = None if system == "auto" else system
        result = service.query(query, force_system=force_system)

        return templates.TemplateResponse("query.html", {
            "request": request,
            "result": result,
            "query": query,
            "selected_system": system
        })
    except Exception as e:
        logger.error(f"Query error: {e}")
        return templates.TemplateResponse("query.html", {
            "request": request,
            "result": None,
            "error": str(e),
            "query": query,
            "selected_system": system
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
    """Export management page."""
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)

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
    """Trigger export pipeline."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

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
async def api_churn_report(request: Request, min_score: int = 7):
    """Get churn risk report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Map score to risk level: 7+ = high only, 5+ = high + medium
        risk_level = 'high' if min_score >= 7 else 'medium'

        # Get actual churn risk data from database
        churn_data = db.get_churn_risk_data(risk_level)

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
            calls_str += f"""
- Call ID: {call['call_id']}
  Date: {call['call_date']}
  Customer: {call['customer_name']} at {call['customer_company']}
  From: {call['from_number']} | To: {call['to_number']}
  Agent: {call['agent']}
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
- Do NOT use placeholder text like [Insert Name]"""

        service = get_query_service()
        result = service.query(prompt, force_system="gemini")

        return {
            "report": "churn_risk",
            "risk_level": risk_level,
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
async def api_customer_report(request: Request, company_name: str):
    """Get customer/company report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Get actual customer data from database
        customer_data = db.get_customer_report(company_name)

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
async def api_quality_report(request: Request, focus: str = "low_quality"):
    """Get call quality report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Get actual quality data from database
        quality_data = db.get_quality_report_data(focus)

        # Format the low quality calls for the prompt
        calls_str = ""
        for call in quality_data.get('low_quality_calls', [])[:15]:
            topics = ", ".join(call['topics'][:3]) if call['topics'] else "N/A"
            improvements = "; ".join(call['improvements'][:3]) if call['improvements'] else "None identified"
            calls_str += f"""
- Date: {call['call_date']}
  PC Recruiter Agent: {call['employee_name']}
  Customer: {call['customer_name']} at {call['customer_company']}
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

        prompt = f"""Generate a Call Quality Analysis Report based on the following ACTUAL DATA.

IMPORTANT: Today's date is {today}. All call dates in this data are from June 2025 onwards. Do NOT include any future dates.

## OVERALL QUALITY METRICS:
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
- Do NOT use placeholder text like [Insert Name]"""

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
async def api_sentiment_report(request: Request, analysis: str = "negative"):
    """Get sentiment analysis report with actual data."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        db = get_db()

        # Get actual sentiment data from database
        sentiment_data = db.get_sentiment_report_data(analysis)

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
            calls_str += f"""
- Date: {call['call_date']}
  PC Recruiter Agent: {call['employee_name']}
  Customer: {call['customer_name']} at {call['customer_company']}
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

        prompt = f"""Generate a Sentiment Analysis Report based on the following ACTUAL DATA from our call center.

IMPORTANT: Today's date is {today}. Do NOT include any dates in the future. All call dates in this data are from June 2025 onwards.

## OVERALL SENTIMENT DISTRIBUTION:
{dist_str}

## PC RECRUITER AGENTS - SENTIMENT BREAKDOWN:
{agent_str or "No agent data available"}

## CUSTOMER COMPANIES WITH NEGATIVE SENTIMENT:
{customer_str or "No customer company data"}

## COMMON TOPICS IN NEGATIVE CALLS:
{topics_str or "No topics identified"}

## WEEKLY SENTIMENT TRENDS (Last 8 weeks):
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
- Reference specific calls by their actual date, agent name, and customer company"""

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
