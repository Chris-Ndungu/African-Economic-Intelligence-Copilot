import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "_docs"
CLAUDE = ROOT / ".claude"
SKILLS = ("add-analysis-function", "add-api-endpoint", "add-playwright-journey")
ROLES = {"PM": "pm", "Backend": "backend", "Frontend": "frontend", "QA": "qa", "Ops": "ops"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def front_matter(path: Path) -> tuple[dict[str, str], str]:
    """Split a Markdown file into its flat `key: value` front matter and body."""
    match = re.match(r"---\n(.*?)\n---\n", read(path), re.S)
    assert match, f"{path} has no front matter"
    fields = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    return fields, read(path)[match.end() :]


def flat(text: str) -> str:
    return " ".join(text.split())


def heading_section(body: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    assert match, f"no '## {heading}' section"
    return match.group(1)


def github_anchor(heading: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def skill(name: str) -> Path:
    return CLAUDE / "skills" / name / "SKILL.md"


def agent(name: str) -> Path:
    return CLAUDE / "agents" / f"{name}.md"


# Skills


@pytest.mark.parametrize("name", SKILLS)
def test_skill_name_matches_folder_and_description_is_one_sentence(name):
    fields, _ = front_matter(skill(name))
    assert fields["name"] == name
    description = fields["description"]
    assert description.startswith("Use when")
    assert len(re.findall(r"[.!?](\s|$)", description)) == 1, description


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_numbered_steps_conventions_tests_and_done_when_last(name):
    _, body = front_matter(skill(name))
    headings = re.findall(r"^## (.+)$", body, re.M)
    assert headings == ["Steps", "Conventions", "Tests to add", "Done when"]
    numbered = re.findall(r"^(\d+)\. ", heading_section(body, "Steps"), re.M)
    assert len(numbered) >= 3
    assert numbered == [str(n) for n in range(1, len(numbered) + 1)]
    done = heading_section(body, "Done when")
    assert re.findall(r"^- \[ \] ", done, re.M), "Done when is not a checklist"
    assert "- [ ] `uv run pytest` passes" in done


def test_analysis_skill_states_its_rules():
    text = flat(read(skill("add-analysis-function")))
    for phrase in (
        "lives in `copilot_core` and imports nothing from FastAPI",
        "Return the Pydantic result models from #11",
        "hypothesis property tests",
        "An empty series",
        "A single data point",
        "Missing periods",
        "Mixed frequencies",
    ):
        assert phrase in text, phrase


def test_endpoint_skill_states_its_rules():
    text = flat(read(skill("add-api-endpoint")))
    for phrase in (
        "Edit the OpenAPI contract first",
        "Validate the contract with `uv run pytest tests/test_web.py`",
        "`openapi-spec-validator`",
        "registered with `include_in_schema=False`",
        "Routes stay thin",
        "Put the logic in `copilot_core`",
        "FastAPI `TestClient`",
        "for the success case",
        "At least one integration test for an error case",
    ):
        assert phrase in text, phrase


def test_endpoint_skill_has_no_type_generation_step():
    _, body = front_matter(skill("add-api-endpoint"))
    done = heading_section(body, "Done when")
    assert "- [ ] `api/openapi.yaml` was edited before the route, and it validates" in done
    assert "types" not in flat(heading_section(body, "Steps")).lower()
    assert "types" not in done.lower()


ARCHITECTURE_LINK = "plan.md#41-application-architecture-fastapi-jinja-and-htmx"


@pytest.mark.parametrize("name", ["add-analysis-function", "add-api-endpoint"])
def test_skill_links_the_current_architecture_section(name):
    assert ARCHITECTURE_LINK in read(skill(name))


def test_playwright_skill_states_its_rules():
    text = flat(read(skill("add-playwright-journey")))
    for phrase in (
        "runs against demo data with the stubbed Gemini client",
        "never calls the real Gemini API or BigQuery",
        "runs under `uv run pytest`",
    ):
        assert phrase in text, phrase


@pytest.mark.parametrize(
    "name, path, issue",
    [
        ("add-analysis-function", "copilot_core/models.py", "#11"),
        ("add-analysis-function", "copilot_core/analysis/", "#16"),
        ("add-api-endpoint", "backend.main:app", "#8"),
        ("add-api-endpoint", "api/openapi.yaml", "#10"),
        ("add-api-endpoint", "openapi-spec-validator", "#74"),
        ("add-playwright-journey", "tests/e2e/", "#34"),
    ],
)
def test_skill_names_the_issue_that_creates_a_missing_path(name, path, issue):
    _, body = front_matter(skill(name))
    # The list item that first mentions the path also names the issue.
    items = re.split(r"\n(?=\d+\. |- )", heading_section(body, "Steps"))
    item = next((i for i in items if path in i), None)
    assert item, f"{path} not in the steps"
    assert issue in item, (path, issue)


# Subagents


def test_one_subagent_per_role_in_agent_team():
    roles = re.findall(r"^## (.+)$", read(DOCS / "agent-team.md"), re.M)
    roles = [r for r in roles if r != "Collaboration"]
    assert sorted(roles) == sorted(ROLES)
    files = sorted(p.stem for p in (CLAUDE / "agents").glob("*.md"))
    assert files == sorted(ROLES.values())


@pytest.mark.parametrize("role, name", ROLES.items())
def test_subagent_states_role_inputs_and_outputs(role, name):
    fields, body = front_matter(agent(name))
    assert fields["name"] == name
    assert fields["description"].startswith("Delegate to the")
    entry = re.search(rf"^## {role}\n(.*?)(?=^## |\Z)", read(DOCS / "agent-team.md"), re.S | re.M)
    team = flat(entry.group(1))
    body = flat(body)
    for field in ("Inputs", "Outputs"):
        expected = re.search(rf"{field}: (.*?)(?= - |$)", team).group(1)
        assert f"- {field}: {expected}" in body, (role, field)
    assert f"_docs/agent-team.md#{name}" in body


@pytest.mark.parametrize("name", ROLES.values())
def test_subagent_says_a_human_merges_and_it_must_not(name):
    body = flat(read(agent(name)))
    assert "A human reviews and merges every PR" in body
    assert "You must never merge a PR" in body


def test_frontend_agent_renders_core_results_with_jinja_and_htmx():
    fields, body = front_matter(agent("frontend"))
    assert "Jinja templates and HTMX" in fields["description"]
    assert "React" not in fields["description"]
    body = flat(body)
    for phrase in (
        "Render the `copilot_core` results",
        "never compute numbers in templates or scripts",
        "Keep HTML routes out of the OpenAPI contract",
        "do not work around it",
        "Show demo data as demo data",
        "never as zero",
    ):
        assert phrase in body, phrase
    assert "TypeScript" not in body


def test_pm_links_its_role_doc_without_copying_it():
    body = read(agent("pm"))
    assert "](../../_docs/team/pm.md)" in body
    for line in read(DOCS / "team" / "pm.md").splitlines():
        line = line.strip("- ").strip()
        if len(line) > 25:
            assert line not in body, f"copied from pm.md: {line}"


def test_pm_has_no_file_editing_tools():
    fields, _ = front_matter(agent("pm"))
    tools = {t.strip() for t in fields["tools"].split(",")}
    assert tools and not tools & {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def test_qa_is_limited_to_tests():
    assert "You may only create or edit files under `tests/`" in flat(read(agent("qa")))


# Links


def claude_files() -> list[Path]:
    return sorted(CLAUDE.rglob("*.md"))


@pytest.mark.parametrize("path", claude_files(), ids=lambda p: p.relative_to(CLAUDE).as_posix())
def test_links_in_claude_files_resolve(path):
    for target, anchor in re.findall(r"\]\(([^)#]+)(?:#([^)]+))?\)", read(path)):
        resolved = path.parent / target
        assert resolved.exists(), target
        if anchor:
            headings = re.findall(r"^#+ (.+)$", read(resolved), re.M)
            assert anchor in {github_anchor(h) for h in headings}, f"{target}#{anchor}"


def test_agents_md_links_every_skill_and_subagent():
    text = read(DOCS / "AGENTS.md")
    match = re.search(r"^Skills and subagents\n(.*?)(?=^Documents\n)", text, re.S | re.M)
    assert match, "no Skills and subagents section"
    entries = re.findall(r"^- \[[^\]]+\]\(([^)]+)\) - (.+)$", match.group(1), re.M)
    linked = {link for link, _ in entries}
    expected = {f"../.claude/skills/{name}/SKILL.md" for name in SKILLS}
    expected |= {f"../.claude/agents/{name}.md" for name in ROLES.values()}
    assert linked == expected
    for link, purpose in entries:
        assert (DOCS / link).exists(), link
        assert purpose.strip(), link
