import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "_docs"
GITHUB = ROOT / ".github"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def strip_front_matter(text: str) -> str:
    match = re.match(r"---\n.*?\n---\n", text, re.S)
    assert match, "issue template has no front matter"
    return text[match.end() :]


def test_process_keeps_roles_and_owner_sections():
    text = read(DOCS / "process.md")
    for heading in ("Roles", "Orchestrator", "Lifecycle", "Rules"):
        assert re.search(rf"^{heading}$", text, re.M), heading
    assert "follows _docs/team/pm.md" in text


def test_process_has_numbered_branch_pr_merge_steps():
    text = read(DOCS / "process.md")
    steps = text.split("Branch, PR and merge", 1)[1].split("Tracker", 1)[0]
    numbered = re.findall(r"^(\d+)\. ", steps, re.M)
    assert numbered == [str(n) for n in range(1, len(numbered) + 1)]
    flat = " ".join(steps.split())
    for phrase in (
        "grooms the issue",
        "one branch, created from an up-to-date `main`",
        "`phase-<number>-<short-description>`",
        "`phase-2-walking-skeleton`",
        "Issues do not get their own branches",
        "`Refs #<issue number>`",
        "`Closes #<issue number>`",
        "A human merges the PR",
        "every acceptance criterion is checked",
        "Agents never merge",
        "The issues close",
    ):
        assert phrase in flat, phrase


def test_board_link_placeholder_in_readme_and_process():
    for path in (ROOT / "README.md", DOCS / "process.md"):
        assert "Project board:" in read(path), path


def test_agent_team_has_one_entry_per_role_with_inputs_and_outputs():
    text = read(DOCS / "agent-team.md")
    for role in ("PM", "Backend", "Frontend", "QA", "Ops"):
        entries = re.findall(rf"^## {role}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        assert len(entries) == 1, role
        for field in ("Responsibilities:", "Inputs:", "Outputs:"):
            assert field in entries[0], (role, field)
    assert "Filled in by #3" not in text


def test_agent_team_links_pm_role_and_states_collaboration_rules():
    text = read(DOCS / "agent-team.md")
    assert "](team/pm.md)" in text
    flat = " ".join(text.split())
    assert (
        "The `copilot_core` result models are the hand-off between backend and "
        "frontend; the OpenAPI contract is the hand-off between the API and its "
        "clients and tests. The contract changes before API behavior does"
    ) in flat
    assert "A human reviews and merges every PR" in flat
    assert "goes back to the PM to re-groom" in flat


def test_agent_team_frontend_role_uses_jinja_and_htmx():
    text = read(DOCS / "agent-team.md")
    entry = " ".join(
        re.search(r"^## Frontend\n(.*?)(?=^## |\Z)", text, re.S | re.M).group(1).split()
    )
    for phrase in (
        "Jinja templates, HTMX partials, CSS and small plain-JavaScript files",
        "rendering the same `copilot_core` results the JSON API returns",
        "Inputs: a groomed issue and the `copilot_core` result models",
    ):
        assert phrase in entry, phrase
    assert "types generated" not in entry


def test_agent_team_links_resolve():
    text = read(DOCS / "agent-team.md")
    for link in re.findall(r"\]\(([^)#]+)", text):
        assert (DOCS / link).exists(), link


def test_issue_template_mirrors_task_template_exactly():
    doc = read(DOCS / "task-template.md")
    assert "Mirrored in `.github/ISSUE_TEMPLATE/task.md`" in doc
    doc_sections = doc[doc.index("## Goal") :].strip()
    issue = strip_front_matter(read(GITHUB / "ISSUE_TEMPLATE" / "task.md")).strip()
    assert issue == doc_sections
    assert re.findall(r"^## (.+)$", issue, re.M) == [
        "Goal",
        "Acceptance criteria",
        "Out of scope",
        "Constraints",
    ]


def test_issue_template_front_matter_names_it():
    text = read(GITHUB / "ISSUE_TEMPLATE" / "task.md")
    assert re.search(r"^name: \S", text, re.M)
    assert re.search(r"^about: \S", text, re.M)


def test_pull_request_template_prefills_checklist():
    text = read(GITHUB / "pull_request_template.md")
    assert re.search(r"^Closes #", text, re.M)
    assert re.search(r"^## Summary$", text, re.M)
    assert re.search(r"^- \[ \] .*acceptance criteri", text, re.M | re.I)
    assert "- [ ] `uv run pytest` passes" in text
