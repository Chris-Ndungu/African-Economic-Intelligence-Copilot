"""The PDF report of a saved investigation (#32, #33).

The report is built only from what was stored: :func:`build_results_view`
gives the same findings, labels, numbers and caveats as the results page, the
charts come from the same figure builder, and every number prints through
:func:`copilot_core.formatting.format_number`, registered here as the Jinja
filter ``number`` just as the web pages do. Nothing here calls Gemini or the
data service. This module has no web-framework imports.

WeasyPrint (which needs Pango) and Plotly with Kaleido (which needs Chrome)
are imported only when a PDF is made, so importing this module never fails on
a machine without them.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from jinja2 import Environment, FileSystemLoader, select_autoescape

from copilot_core.figures import ChartView
from copilot_core.findings_view import (
    FindingCard,
    MethodView,
    ResultsView,
    SourceView,
    build_results_view,
)
from copilot_core.formatting import format_number
from copilot_core.history import utc_date, utc_text
from copilot_core.meta import banner_text
from copilot_core.schemas import Investigation, Meta

__all__ = [
    "CHART_FAILED_TEXT",
    "InvestigationNotExportableError",
    "ReportChart",
    "ReportView",
    "build_report_view",
    "render_chart_image",
    "render_report_html",
    "render_report_pdf",
    "report_filename",
    "url_allowed",
]

logger = logging.getLogger("copilot_core.report")

TEMPLATES_DIR = Path(__file__).resolve().parent / "report_templates"
CHART_FAILED_TEXT = "Chart could not be rendered"
CHART_WIDTH, CHART_HEIGHT, CHART_SCALE = 800, 420, 2

ChartRenderer = Callable[[dict[str, Any]], bytes]


class InvestigationNotExportableError(Exception):
    """Only a ``succeeded`` investigation can be exported."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Only succeeded investigations can be exported. This one is {status}.")


@dataclass(frozen=True)
class ReportChart:
    id: str
    view: ChartView
    image: str | None = None
    """A ``data:`` URI of the rendered chart, or ``None``."""
    failed: bool = False


@dataclass(frozen=True)
class ReportView:
    title: str
    results: ResultsView
    banner: str
    generated_text: str
    methods: list[MethodView] = field(default_factory=list)
    sources: list[SourceView] = field(default_factory=list)
    charts: dict[str, ReportChart] = field(default_factory=dict)
    """Every chart by its ID."""
    placed: dict[str, list[ReportChart]] = field(default_factory=dict)
    """Charts printed under the finding card that first cites them, by card ID."""
    unplaced: list[ReportChart] = field(default_factory=list)
    """Charts no finding cites."""


def report_filename(investigation: Investigation) -> str:
    """``investigation-<YYYY-MM-DD>-<first 8 characters of the id>.pdf``."""
    return f"investigation-{utc_date(investigation.created_at)}-{str(investigation.id)[:8]}.pdf"


def _banner(data_mode: str, snapshot_date: date | None) -> str:
    if data_mode == "demo" and snapshot_date is None:
        return "Sample data (snapshot date unknown). Not live economic data."
    mode = data_mode if data_mode in ("demo", "live") else "unknown"
    meta = Meta(data_mode=cast(Any, mode), snapshot_date=snapshot_date, gemini_configured=False)
    return banner_text(meta)


def _cards(view: ResultsView) -> list[FindingCard]:
    return [*view.facts, *view.unverified, *view.hypotheses]


def _all_sources(investigation: Investigation, view: ResultsView) -> list[SourceView]:
    sources: dict[str, SourceView] = {}
    for card in _cards(view):
        for source in card.sources:
            sources.setdefault(source.id, source)
    if investigation.result is not None:
        for ref in investigation.result.sources:
            sources.setdefault(
                ref.id,
                SourceView(
                    ref.id,
                    ref.name,
                    ref.provider,
                    str(ref.url) if ref.url else None,
                    ref.last_updated,
                ),
            )
    return list(sources.values())


def build_report_view(
    investigation: Investigation,
    *,
    snapshot_date: date | None = None,
    generated_at: datetime | None = None,
    chart_images: dict[str, str | None] | None = None,
) -> ReportView:
    """What the report template prints.

    ``chart_images`` maps a chart ID to its image URI, or to ``None`` when
    the chart failed to render; a chart missing from it has no image.
    """
    if investigation.status != "succeeded":
        raise InvestigationNotExportableError(investigation.status)
    results = build_results_view(investigation)
    images = chart_images or {}
    charts = {
        block.id: ReportChart(
            block.id,
            block.view,
            image=images.get(block.id),
            failed=block.id in images and images[block.id] is None,
        )
        for block in results.charts
    }
    placed: dict[str, list[ReportChart]] = {}
    seen: set[str] = set()
    for card in _cards(results):
        for chart_id in card.chart_ids:
            if chart_id in charts and chart_id not in seen:
                seen.add(chart_id)
                placed.setdefault(card.id, []).append(charts[chart_id])
    return ReportView(
        title=investigation.title,
        results=results,
        banner=_banner(investigation.data_mode, snapshot_date),
        generated_text=utc_text(generated_at or datetime.now(UTC)),
        methods=list(dict.fromkeys(m for card in _cards(results) for m in card.methods)),
        sources=_all_sources(investigation, results),
        charts=charts,
        placed=placed,
        unplaced=[c for cid, c in charts.items() if cid not in seen],
    )


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["number"] = format_number
    return env


# --- Charts -------------------------------------------------------------------


def render_chart_image(figure: dict[str, Any]) -> bytes:
    """A PNG of a figure dict, drawn with Plotly and Kaleido.

    Raises if Kaleido or its Chrome is missing or the figure is rejected.
    """
    import plotly.io as pio

    image: bytes = pio.to_image(
        figure, format="png", width=CHART_WIDTH, height=CHART_HEIGHT, scale=CHART_SCALE
    )
    return image


def _chart_images(investigation: Investigation, render: ChartRenderer) -> dict[str, str | None]:
    images: dict[str, str | None] = {}
    for block in build_results_view(investigation).charts:
        figure = block.view.figure
        if figure is None:
            continue  # empty or unsupported: the report prints the reason instead
        try:
            png = render(figure)
        except Exception:
            logger.exception(
                "chart %s could not be rendered for investigation %s",
                block.id,
                investigation.id,
            )
            images[block.id] = None
        else:
            images[block.id] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return images


# --- Rendering ----------------------------------------------------------------


def render_report_html(
    investigation: Investigation,
    *,
    snapshot_date: date | None = None,
    generated_at: datetime | None = None,
    charts: bool = True,
    render_chart: ChartRenderer | None = None,
) -> str:
    """The report as HTML, with every stored text escaped by Jinja2."""
    if investigation.status != "succeeded":
        raise InvestigationNotExportableError(investigation.status)
    images = _chart_images(investigation, render_chart or render_chart_image) if charts else None
    view = build_report_view(
        investigation,
        snapshot_date=snapshot_date,
        generated_at=generated_at,
        chart_images=images,
    )
    return _environment().get_template("report.html").render(report=view, v=view.results)


def url_allowed(url: str) -> bool:
    """Whether the report may load ``url``.

    Only ``data:`` URIs and files inside the report's own template folder
    are allowed. ``file://`` URLs elsewhere, ``http://`` and ``https://``
    are refused, whatever the stored text says.
    """
    parsed = urlparse(url)
    if parsed.scheme == "data":
        return True
    if parsed.scheme == "file":
        try:
            Path(url2pathname(unquote(parsed.path))).resolve().relative_to(TEMPLATES_DIR.resolve())
        except (ValueError, OSError):
            return False
        return not parsed.netloc or parsed.netloc == "localhost"
    return False


def make_url_fetcher() -> Any:
    """A WeasyPrint URL fetcher that refuses everything but bundled assets."""
    from weasyprint.urls import URLFetcher

    class ReportURLFetcher(URLFetcher):
        def fetch(self, url: str, headers: Any = None) -> Any:
            if not url_allowed(url):
                raise ValueError(f"The report may not load {url.split(':', 1)[0]!r} URLs.")
            return super().fetch(url, headers)

    return ReportURLFetcher(allowed_protocols={"data", "file"}, allow_redirects=False)


def render_report_pdf(
    investigation: Investigation,
    *,
    snapshot_date: date | None = None,
    generated_at: datetime | None = None,
    charts: bool = True,
    render_chart: ChartRenderer | None = None,
) -> bytes:
    """The report as PDF bytes."""
    html = render_report_html(
        investigation,
        snapshot_date=snapshot_date,
        generated_at=generated_at,
        charts=charts,
        render_chart=render_chart,
    )
    from weasyprint import HTML

    pdf: bytes = HTML(string=html, url_fetcher=make_url_fetcher()).write_pdf()
    return pdf
