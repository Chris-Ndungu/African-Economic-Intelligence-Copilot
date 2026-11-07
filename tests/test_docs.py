import re
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
        "api.md": "#10",
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
    present |= {p.name for p in ROOT.iterdir() if p.name in {".gitignore", ".python-version", ".github"}}
    assert listed - present == set(), "layout lists paths that do not exist"
    assert present - listed == set(), "layout is missing top-level paths"


def test_root_pointers_load_agents_md():
    assert "@_docs/AGENTS.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "_docs/AGENTS.md" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
