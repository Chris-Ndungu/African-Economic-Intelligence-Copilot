"""Checks on the bundled demo snapshot in data/demo (#7).

They read the files as bytes and text only, so they need no Parquet library.
"""

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
TABLES = ["dim_country", "dim_indicator", "fact_fx_rates", "fact_macroeconomic_indicators"]


def test_one_parquet_file_per_table_the_copilot_reads():
    assert sorted(p.stem for p in DEMO.glob("*.parquet")) == sorted(TABLES)
    for table in TABLES:
        data = (DEMO / f"{table}.parquet").read_bytes()
        assert data[:4] == b"PAR1" and data[-4:] == b"PAR1", table


def test_snapshot_is_at_most_20_mb():
    total = sum(p.stat().st_size for p in DEMO.rglob("*") if p.is_file())
    assert total <= 20 * 1024 * 1024


def test_readme_says_sample_data_first():
    first_lines = "\n".join((DEMO / "README.md").read_text(encoding="utf-8").splitlines()[:4])
    assert "sample data, not live data" in first_lines


def test_readme_gives_the_build_command_and_provenance():
    readme = (DEMO / "README.md").read_text(encoding="utf-8")
    assert "uv run --with duckdb==1.4.1 python data/demo/build_snapshot.py <csv-dir>" in readme
    assert "2026-11-11" in readme
    assert "e61e67a606e60e2631dc98a9e1a2949cee60087e" in readme
    for source in ("International Monetary Fund", "World Bank", "ExchangeRate-API"):
        assert source in readme


def test_script_keeps_exactly_the_supported_indicators():
    tree = ast.parse((DEMO / "build_snapshot.py").read_text(encoding="utf-8"))
    script_codes = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "SUPPORTED_INDICATORS"
    )
    contract = (ROOT / "_docs" / "data-contract.md").read_text(encoding="utf-8")
    supported = contract[contract.index("### Supported indicators") :]
    table = supported[: supported.index("Indicators in `dim_indicator` that are not offered")]
    doc_codes = re.findall(r"^\| `([A-Z][A-Z0-9_.]+)` \| ", table, re.M)
    assert sorted(script_codes) == sorted(doc_codes)


def test_no_data_exports_are_committed():
    tracked = subprocess.run(
        ["git", "ls-files", "*.csv"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert tracked in ([], ["_docs/coverage.csv"])
