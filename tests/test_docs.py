import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "_docs"
AGENTS = DOCS / "AGENTS.md"


def section(name: str) -> str:
    """Return the body of a bare-word section in _docs/AGENTS.md."""
    text = AGENTS.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\n(.*?)(?=^[A-Z][^\n]*\n\n|\Z)", text, re.S | re.M)
    assert match, f"section {name!r} not found in _docs/AGENTS.md"
    return match.group(1)


def test_every_doc_is_linked_from_documents_section():
    linked = set(re.findall(r"\]\(([^)#]+)", section("Documents")))
    docs = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}
    docs.discard("AGENTS.md")
    assert docs - linked == set(), "docs missing from the Documents section"


def test_every_link_in_agents_md_resolves():
    links = re.findall(r"\]\(([^)#]+)", AGENTS.read_text(encoding="utf-8"))
    broken = [link for link in links if not (DOCS / link).exists()]
    assert broken == []


def github_anchor(heading: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def test_every_anchor_in_agents_md_matches_a_heading():
    text = AGENTS.read_text(encoding="utf-8")
    for target, anchor in re.findall(r"\]\(([^)#]+)#([^)]+)\)", text):
        headings = re.findall(r"^#+ (.+)$", (DOCS / target).read_text(encoding="utf-8"), re.M)
        assert anchor in {github_anchor(h) for h in headings}, f"{target}#{anchor}"


def test_product_section_is_at_most_five_sentences():
    product = " ".join(section("Product").split())
    sentences = [s for s in re.split(r"(?<=\.)\s+", product) if s]
    assert 0 < len(sentences) <= 5


def test_conventions_state_the_required_rules():
    conventions = " ".join(section("Conventions").split())
    for phrase in (
        "Business logic lives in `copilot_core`, with no web-framework imports",
        "FastAPI routes in `backend/` stay thin",
        "Tests live in `tests/` and run with `uv run pytest`",
        "The OpenAPI contract changes before API behavior does",
        "plan.md#8-",
    ):
        assert phrase in conventions


def test_commands_and_rules_keep_their_original_lines():
    assert "- `uv sync` - install dependencies" in section("Commands")
    assert "- `uv run pytest` - the whole suite" in section("Commands")
    rules = " ".join(section("Rules").split())
    assert "Dependencies are added in `pyproject.toml`. Do not add one without asking" in rules


def test_placeholders_name_the_issue_that_fills_them():
    expected = {
        "architecture.md": "#54",
        "data-contract.md": "#5 and #6",
    }
    for name, issue in expected.items():
        text = (DOCS / name).read_text(encoding="utf-8")
        assert text.startswith("# "), f"{name} has no heading"
        assert f"Filled in by {issue}." in text, name


def test_layout_matches_repository_root():
    listed = {
        name.rstrip("/")
        for name in re.findall(r"^- `([^`]+)`", section("Repository layout"), re.M)
    }
    present = {p.name for p in ROOT.iterdir() if not p.name.startswith(".")}
    present |= {p.name for p in ROOT.iterdir() if p.name in {".gitignore", ".python-version", ".github", ".claude"}}
    assert listed - present == set(), "layout lists paths that do not exist"
    assert present - listed == set(), "layout is missing top-level paths"


def test_root_pointers_load_agents_md():
    assert "@_docs/AGENTS.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "_docs/AGENTS.md" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_api_md_documents_the_contract_and_its_conventions():
    text = (DOCS / "api.md").read_text(encoding="utf-8")
    assert "Filled in by" not in text
    for phrase in (
        "api/openapi.yaml",
        "The OpenAPI contract changes before API behavior does",
        "validated by `uv run pytest`",
        "`openapi-spec-validator`",
        "`data_mode`",
        "`Error`",
        "`503`",
        "`null`, never `0`",
        "plan.md",
    ):
        assert phrase in text, phrase


def test_api_md_explains_html_routes_are_outside_the_contract():
    text = (DOCS / "api.md").read_text(encoding="utf-8")
    first_line = text.split("\n## ", 1)[0]
    contract_first = text.split("## The contract changes first", 1)[1].split("\n## ", 1)[0]
    assert "frontend types" not in first_line.lower()
    assert "frontend types" not in contract_first.lower()
    assert "Regenerating frontend types" not in text
    match = re.search(r"^## HTML routes\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, "no HTML routes section"
    html_routes = " ".join(match.group(1).split())
    for phrase in ("outside the contract", "`include_in_schema=False`", "/partials/"):
        assert phrase in html_routes, phrase


def test_commands_run_the_app_and_validate_the_contract():
    commands = " ".join(section("Commands").split())
    assert (
        "- `uv run uvicorn backend.main:app --reload` - serve the pages and the API "
        "at `http://localhost:8000`"
    ) in commands
    assert "`api/openapi.yaml` is validated by `uv run pytest`" in commands


# Built from parts, so this file does not itself contain what it bans.
NODE_COMMANDS = re.compile(r"\b(?:" + "np" + "m|np" + "x)\b|gen" + "-types|check" + "-types")
OLD_ANCHOR = "fastapi-" + "-react"


def test_no_node_commands_are_left():
    paths = [AGENTS, DOCS / "api.md", ROOT / "README.md"]
    paths += [p for p in (ROOT / ".claude").rglob("*") if p.is_file()]
    paths += list((ROOT / "tests").rglob("*.py"))
    found = [
        p.relative_to(ROOT).as_posix()
        for p in paths
        if NODE_COMMANDS.search(p.read_text(encoding="utf-8"))
    ]
    assert found == []


def test_frontend_folder_and_node_ignore_rules_are_gone():
    assert not (ROOT / "frontend").exists()
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "node_modules/" not in ignored
    assert "# Node" not in ignored
    assert "dist/" in ignored


def test_readme_says_how_to_run_locally():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"^## Run locally\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, "no Run locally section"
    assert "uv run uvicorn backend.main:app --reload" in match.group(1)
    assert "http://localhost:8000" in match.group(1)
    assert not NODE_COMMANDS.search(text)


def plan_section(heading: str) -> str:
    text = (DOCS / "plan.md").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^#+ |\Z)", text, re.S | re.M)
    assert match, heading
    return " ".join(match.group(1).split())


def test_plan_architecture_is_fastapi_jinja_and_htmx():
    body = plan_section("### 4.1 Application architecture: FastAPI, Jinja and HTMX")
    for phrase in (
        "FastAPI serves server-rendered Jinja pages and HTMX partials, and a JSON API "
        "defined contract-first in `api/openapi.yaml`. Both are thin routes over `copilot_core`",
        "HTMX with the SSE extension",
        "Plotly.js",
        "all vendored static files",
        "HTML routes",
        "JSON API routes",
        "One language the owner can review end to end",
        "No Node toolchain and no frontend build step",
        "the Python number formatter, and the Python chart builder",
        "One process serves",
        "**React + TypeScript SPA (Vite, Tailwind, shadcn/ui, TanStack Query):** Rejected",
        "The owner does not know React and must be able to review and own all the code",
        "scaffolded in #9 and #10",
        "**Streamlit monolith:**",
        "**Python full-stack frameworks (Reflex, Dash, NiceGUI):**",
        "HTML routes are outside the OpenAPI contract and are registered with "
        "`include_in_schema=False`",
        "Templates and browser scripts display `copilot_core` results; "
        "they never compute new numbers",
    ):
        assert phrase in body, phrase
    for gone in ("openapi-typescript", "FastAPI + HTMX/Jinja", "single-page application"):
        assert gone not in body, gone


def test_plan_names_the_toolchain_only_as_the_rejected_alternative():
    text = (DOCS / "plan.md").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if "**React + TypeScript SPA" not in line]
    for word in ("React", "Vite", "TanStack", "Vitest", "openapi-typescript"):
        assert not [line for line in lines if word in line], word
    assert "regenerate frontend types" not in text
    assert "Scaffold the FastAPI app with the Jinja and HTMX workspace shell" in text


def test_no_file_links_to_the_old_architecture_anchor():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    found = [
        name
        for name in tracked
        if Path(name).suffix in {".md", ".py", ".yaml", ".toml", ".html"}
        and (ROOT / name).exists()
        and OLD_ANCHOR in (ROOT / name).read_text(encoding="utf-8")
    ]
    assert found == []


def test_backlog_marks_the_react_tasks_superseded():
    text = (DOCS / "task.md").read_text(encoding="utf-8")
    for number in (9, 10):
        entry = re.search(rf"^## {number}\. .*?(?=^## |\Z)", text, re.S | re.M).group(0)
        assert "Superseded by #74" in entry, number
