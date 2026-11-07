"""HTML routes: server-rendered Jinja pages and HTMX partials.

These routes are outside the OpenAPI contract, so the router is registered
with `include_in_schema=False`. Like the JSON routes they stay thin: read
input, call `copilot_core`, render a template. They never call the JSON API
over HTTP.

- Full pages: `GET /` (and `GET /investigations/{id}`, added in #23)
- HTMX fragments: under `/partials/...`
- Static files: served at `/static/...` from `backend/static/`
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"

# The vendored HTMX file, pinned to an exact release. See
# backend/static/vendor/README.md for its source URL and SHA-256.
HTMX_FILE = "vendor/htmx-2.0.11.min.js"

# Jinja2Templates turns autoescaping on for `.html` templates, so any value
# a page renders is escaped unless a template marks it safe.
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["htmx_file"] = HTMX_FILE

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def workspace(request: Request) -> HTMLResponse:
    """The empty workspace shell."""
    return templates.TemplateResponse(request, "pages/workspace.html")
