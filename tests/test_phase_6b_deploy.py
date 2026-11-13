"""Static checks for the Phase 6B deployment criteria (#37 to #40)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SECRET_KEYS = {"DATABASE_URL", "COPILOT_GEMINI_API_KEY", "COPILOT_RATE_LIMIT_SALT"}
IMAGE = "ghcr.io/chris-ndungu/african-economic-intelligence-copilot"


def _services() -> dict[str, dict]:
    data = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    return {s["name"]: s for s in data["services"]}


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    return wf.get("on", wf.get(True))


def test_render_blueprint_declares_both_services_on_the_free_plan() -> None:
    services = _services()
    assert set(services) == {"copilot-dev", "copilot-prod"}
    for svc in services.values():
        assert svc["plan"] == "free"
        assert svc["healthCheckPath"] == "/health"
        assert svc["image"]["url"].startswith(IMAGE)
        assert svc.get("region")


def test_render_secrets_have_no_values() -> None:
    for svc in _services().values():
        env = {e["key"]: e for e in svc["envVars"]}
        assert SECRET_KEYS <= set(env)
        for key in SECRET_KEYS:
            assert env[key].get("sync") is False
            assert "value" not in env[key]
        for key, entry in env.items():
            if key not in SECRET_KEYS:
                assert "sync" not in entry or entry["sync"] is not False
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert not re.search(r"postgres(ql)?(\+\w+)?://\w+:[^@\s]+@", text)
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", text)


def test_render_environments_are_distinct() -> None:
    services = _services()
    dev = {e["key"]: e.get("value") for e in services["copilot-dev"]["envVars"]}
    prod = {e["key"]: e.get("value") for e in services["copilot-prod"]["envVars"]}
    assert dev["COPILOT_DEPLOYMENT_ENVIRONMENT"] == "dev"
    assert prod["COPILOT_DEPLOYMENT_ENVIRONMENT"] == "prod"
    assert prod["COPILOT_ENVIRONMENT"] == "prod"
    assert dev["LLM_CLIENT"] == prod["LLM_CLIENT"] == "gemini"


def test_deploy_dev_trigger_and_environment() -> None:
    wf = _workflow("deploy-dev.yml")
    trig = _triggers(wf)
    assert set(trig) == {"workflow_run"}
    assert trig["workflow_run"]["workflows"] == ["CI"]
    assert trig["workflow_run"]["branches"] == ["main"]
    deploy = wf["jobs"]["deploy"]
    assert deploy["environment"]["name"] == "dev"
    assert deploy["concurrency"]["cancel-in-progress"] is False
    assert wf["jobs"]["build"]["permissions"]["packages"] == "write"
    assert "success" in wf["jobs"]["build"]["if"]


def test_deploy_prod_trigger_and_environment() -> None:
    wf = _workflow("deploy-prod.yml")
    trig = _triggers(wf)
    assert set(trig) == {"push"}
    assert trig["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+"]
    deploy = wf["jobs"]["deploy"]
    assert deploy["environment"]["name"] == "prod"
    assert deploy["needs"] == "verify"
    assert "environment" not in wf["jobs"]["verify"]
    assert deploy["concurrency"]["cancel-in-progress"] is False
    text = (ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")
    assert "build-push-action" not in text  # promoted, never rebuilt


def test_workflows_pin_action_versions() -> None:
    for name in ("deploy-dev.yml", "deploy-prod.yml"):
        text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s*(\S+)", text)
        assert uses
        for ref in uses:
            assert re.search(r"@v?\d+\.\d+\.\d+$|@[0-9a-f]{40}$", ref), ref


def test_deploy_secrets_are_never_echoed() -> None:
    names = ("RENDER_DEPLOY_HOOK_URL", "RENDER_API_KEY", "DATABASE_URL")
    files = [
        ROOT / ".github/workflows/deploy-dev.yml",
        ROOT / ".github/workflows/deploy-prod.yml",
        ROOT / ".github/scripts/render-deploy.sh",
    ]
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\b(echo|printf|set -x)\b", line):
                assert not any(n in line for n in names), f"{path.name}: {line.strip()}"
    script = (ROOT / ".github/scripts/render-deploy.sh").read_text(encoding="utf-8")
    assert "set -x" not in script
    assert "docker run --rm -e DATABASE_URL " in script


def test_deploy_docs_are_linked_and_complete() -> None:
    agents = (ROOT / "_docs/AGENTS.md").read_text(encoding="utf-8")
    assert "(deployment.md)" in agents
    doc = (ROOT / "_docs/deployment.md").read_text(encoding="utf-8")
    for heading in ("Deploy dev by hand", "Release to prod", "Roll back by hand"):
        assert heading in doc
    for phrase in ("15 minutes", "512 MB", "forks", "whole Render account"):
        assert phrase in doc
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "copilot-dev" in readme and "copilot-prod" in readme
    assert "up to a minute" in readme
