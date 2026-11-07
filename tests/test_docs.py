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


def test_layout_matches_repository_root():
    listed = {
        name.rstrip("/")
        for name in re.findall(r"^- `([^`]+)`", section("Repository layout"), re.M)
    }
    present = {p.name for p in ROOT.iterdir() if not p.name.startswith(".")}
    present |= {p.name for p in ROOT.iterdir() if p.name in {".gitignore", ".python-version"}}
    assert listed - present == set(), "layout lists paths that do not exist"
    assert present - listed == set(), "layout is missing top-level paths"


def test_root_pointers_load_agents_md():
    assert "@_docs/AGENTS.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "_docs/AGENTS.md" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
