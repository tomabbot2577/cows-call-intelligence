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

    return templates.TemplateResponse("reports.html", {"request": request})


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
    """Get churn risk report."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        service = get_query_service()
        query = f"List all calls with churn risk score >= {min_score}. Include customer name, company, score, reason, and recommended action."
        result = service.query(query, force_system="vertex")

        return {
            "report": "churn_risk",
            "min_score": min_score,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Churn report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/rag/reports/agent/{agent_name}")
async def api_agent_report(request: Request, agent_name: str, date: Optional[str] = None):
    """Get agent performance report."""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        service = get_query_service()
        query = f"Analyze agent {agent_name}'s calls"
        if date:
            query += f" from {date}"
        query += ". Provide: total calls, average quality score, strengths, areas for improvement, and coaching recommendations."

        result = service.query(query, force_system="vertex")

        return {
            "report": "agent_performance",
            "agent": agent_name,
            "date": date,
            "response": result["response"],
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Agent report error: {e}")
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
