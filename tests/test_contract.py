"""The FastAPI app matches the committed OpenAPI contract (#57).

``api/openapi.yaml`` is the hand-off between the API and its clients. These
tests compare the schema FastAPI generates with it: every path and method,
the query and path parameters, the request body and every response schema,
with ``$ref``, ``allOf`` and nullable unions resolved on both sides so only
the shape is compared.

Compared: types (``null`` included), object properties and required fields,
array items, enum values and string formats.

Ignored, because they do not change what a client sends or receives:

- descriptions, summaries, titles, examples, defaults and operation ids
- the order of paths, properties, required fields and enum values
- schema names: a ``$ref`` is compared by what it points to
- FastAPI's default ``422`` response, when the contract leaves ``422`` out
- the value schema of a map (``additionalProperties``), such as method
  parameters; ``tests/test_models.py`` covers those
- validation constraints such as ``pattern``, ``minLength`` or ``maximum``;
  the model tests cover those

HTML pages, HTMX partials and the static mount are not part of the contract.
They are registered with ``include_in_schema=False`` (#74), so they never
appear in the generated schema; the OTLP forwarding endpoint (#44) will be
too. Any generated path that is neither ``/health`` nor under ``/api/``
fails the test.
"""

import copy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from openapi_spec_validator.readers import read_from_filename
from pydantic import BaseModel

from backend.main import create_app
from backend.settings import Settings
from copilot_core.schemas import Country, Investigation, InvestigationResult

ROOT = Path(__file__).resolve().parent.parent
METHODS = ("get", "post", "put", "patch", "delete")

# Operations in the contract that later issues implement.
NOT_YET_IMPLEMENTED: dict[tuple[str, str], str] = {}


def contract() -> dict[str, Any]:
    spec, _ = read_from_filename(str(ROOT / "api" / "openapi.yaml"))
    return dict(spec)


def generated(app: FastAPI | None = None) -> dict[str, Any]:
    app = app or create_app(Settings())
    app.openapi_schema = None
    return app.openapi()


# --- Normalizing ---------------------------------------------------------------


def _resolve(schema: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        node: Any = doc
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        schema = {**node, **{k: v for k, v in schema.items() if k != "$ref"}}
    return schema


def normalize(schema: dict[str, Any] | None, doc: dict[str, Any]) -> dict[str, Any]:
    """The shape of a schema: types, properties, required, items, enum, format."""
    if not schema:
        return {}
    schema = _resolve(schema, doc)
    out: dict[str, Any] = {}

    for key in ("allOf",):
        for part in schema.get(key, []):
            merged = normalize(part, doc)
            out.setdefault("properties", {}).update(merged.get("properties", {}))
            out["required"] = sorted(set(out.get("required", [])) | set(merged.get("required", [])))
            if "types" in merged:
                out["types"] = merged["types"]

    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        normalized = [normalize(v, doc) for v in variants]
        nullable = any(v == {"types": ["null"]} for v in normalized)
        rest = [v for v in normalized if v != {"types": ["null"]}]
        if len(rest) == 1:
            out.update(rest[0])
        elif all(set(v) <= {"types"} for v in rest):
            out["types"] = sorted({t for v in rest for t in v["types"]})
        else:
            out["anyOf"] = sorted(rest, key=repr)
        if nullable:
            out["types"] = sorted(set(out.get("types", ["object"])) | {"null"})

    types = schema.get("type")
    if types is not None:
        found = {types} if isinstance(types, str) else set(types)
        out["types"] = sorted(found | set(out.get("types", [])))
    if "integer" in out.get("types", []) and "number" in out.get("types", []):
        out["types"].remove("integer")
    if "const" in schema:
        out["enum"] = [schema["const"]]
    if "enum" in schema:
        out["enum"] = sorted(v for v in schema["enum"] if v is not None)
    if "format" in schema:
        out["format"] = schema["format"]
    if "properties" in schema:
        props = out.setdefault("properties", {})
        for name, sub in schema["properties"].items():
            props[name] = normalize(sub, doc)
        out["required"] = sorted(set(out.get("required", [])) | set(schema.get("required", [])))
    if "items" in schema:
        out["items"] = normalize(schema["items"], doc)
    if "properties" in out or "additionalProperties" in schema:
        out["types"] = sorted(set(out.get("types", [])) | {"object"})
    return out


def differences(app: dict[str, Any], spec: dict[str, Any], where: str) -> list[str]:
    """Differences between two normalized schemas, each naming the field."""
    found: list[str] = []
    for key in ("types", "enum", "format", "required"):
        if app.get(key) != spec.get(key):
            found.append(
                f"{where}: {key} is {app.get(key)} in the app, {spec.get(key)} in the contract"
            )
    app_props, spec_props = app.get("properties", {}), spec.get("properties", {})
    for name in sorted(set(app_props) | set(spec_props)):
        field = f"{where}.{name}"
        if name not in spec_props:
            found.append(f"{field}: in the app, not in the contract")
        elif name not in app_props:
            found.append(f"{field}: in the contract, not in the app")
        else:
            found += differences(app_props[name], spec_props[name], field)
    if "items" in app or "items" in spec:
        found += differences(app.get("items", {}), spec.get("items", {}), f"{where}[]")
    if app.get("anyOf") != spec.get("anyOf"):
        found.append(f"{where}: union variants differ")
    return found


# --- Comparing operations ---------------------------------------------------------


def operations(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    ops = {}
    for path, item in doc["paths"].items():
        shared = item.get("parameters", [])
        for method in METHODS:
            if method in item:
                op = dict(item[method])
                op["parameters"] = shared + op.get("parameters", [])
                ops[(method.upper(), path)] = op
    return ops


def _json_schema(container: dict[str, Any] | None, doc: dict[str, Any]) -> dict[str, Any]:
    if not container:
        return {}
    container = _resolve(container, doc)
    return normalize(container.get("content", {}).get("application/json", {}).get("schema"), doc)


def contract_differences(app_doc: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    found: list[str] = []
    app_ops, spec_ops = operations(app_doc), operations(spec)
    for method, path in sorted(app_ops):
        if path != "/health" and not path.startswith("/api/"):
            found.append(f"{method} {path}: generated path is neither /health nor under /api/")
        if (method, path) not in spec_ops:
            found.append(f"{method} {path}: endpoint is in the app but not in the contract")
    for key in sorted(spec_ops):
        if key not in app_ops and key not in NOT_YET_IMPLEMENTED:
            found.append(f"{key[0]} {key[1]}: endpoint is in the contract but not in the app")

    for key in sorted(set(app_ops) & set(spec_ops)):
        name = f"{key[0]} {key[1]}"
        app_op, spec_op = app_ops[key], spec_ops[key]

        app_params = {(p["in"], p["name"]): _resolve(p, app_doc) for p in app_op["parameters"]}
        resolved = [_resolve(q, spec) for q in spec_op["parameters"]]
        spec_params = {(p["in"], p["name"]): p for p in resolved}
        if set(app_params) != set(spec_params):
            found.append(f"{name}: parameters {sorted(app_params)} != {sorted(spec_params)}")
        for pkey in set(app_params) & set(spec_params):
            a, s = app_params[pkey], spec_params[pkey]
            if bool(a.get("required")) != bool(s.get("required")):
                found.append(f"{name} parameter {pkey[1]}: required differs")
            found += differences(
                normalize(a.get("schema"), app_doc),
                normalize(s.get("schema"), spec),
                f"{name} parameter {pkey[1]}",
            )

        found += differences(
            _json_schema(app_op.get("requestBody"), app_doc),
            _json_schema(spec_op.get("requestBody"), spec),
            f"{name} request body",
        )

        app_codes, spec_codes = set(app_op["responses"]), set(spec_op["responses"])
        if "422" not in spec_codes:
            app_codes.discard("422")  # FastAPI's default validation response
        if app_codes != spec_codes:
            found.append(f"{name}: responses {sorted(app_codes)} != {sorted(spec_codes)}")
        for code in sorted(app_codes & spec_codes):
            found += differences(
                _json_schema(app_op["responses"][code], app_doc),
                _json_schema(spec_op["responses"][code], spec),
                f"{name} {code}",
            )
    return found


# --- Tests ---------------------------------------------------------------------


def test_app_matches_the_contract():
    found = contract_differences(generated(), contract())
    assert not found, "The app and api/openapi.yaml differ:\n" + "\n".join(found)


def test_pending_operations_are_still_missing_from_the_app():
    """Remove an entry from NOT_YET_IMPLEMENTED when its issue adds the endpoint."""
    app_ops = operations(generated())
    for key, issue in NOT_YET_IMPLEMENTED.items():
        assert key not in app_ops, f"{key} is implemented; remove it ({issue}) from the list"


def test_an_endpoint_missing_from_the_contract_fails_naming_it():
    app = create_app(Settings())

    @app.get("/api/extra")
    def extra() -> dict[str, str]:
        return {}

    found = contract_differences(generated(app), contract())
    assert any("GET /api/extra" in d and "not in the contract" in d for d in found)


def test_a_changed_field_type_fails_naming_the_field():
    class CountryWithNumericRegion(BaseModel):
        code: str
        name: str
        region: int | None

    class BrokenCountryList(BaseModel):
        data_mode: str
        countries: list[CountryWithNumericRegion]

    app = create_app(Settings())
    app.router.routes = [
        r for r in app.router.routes if getattr(r, "path", None) != "/api/countries"
    ]

    @app.get("/api/countries", responses={500: {}, 503: {}})
    def countries() -> BrokenCountryList:
        raise NotImplementedError

    found = contract_differences(generated(app), contract())
    assert any(".countries[].region: types" in d for d in found), found
    assert Country.model_fields["region"].annotation == str | None


def test_cosmetic_differences_are_ignored():
    spec = copy.deepcopy(contract())
    spec["paths"]["/api/countries"]["get"]["description"] = "Changed."
    schemas = spec["components"]["schemas"]
    schemas["Country"]["required"] = list(reversed(schemas["Country"]["required"]))
    schemas["Country"]["properties"] = dict(
        reversed(list(schemas["Country"]["properties"].items()))
    )
    assert contract_differences(generated(), spec) == []


def test_a_path_outside_api_fails():
    app = create_app(Settings())

    @app.get("/other")
    def other() -> dict[str, str]:
        return {}

    found = contract_differences(generated(app), contract())
    assert any("GET /other: generated path is neither /health nor under /api/" in d for d in found)


@pytest.mark.parametrize("path", ["/", "/partials/trend", "/partials/investigations", "/static"])
def test_pages_partials_and_static_files_are_not_in_the_schema(path):
    assert path not in generated()["paths"]


def test_contract_examples_validate_against_the_models():
    examples = contract()["components"]["examples"]
    InvestigationResult.model_validate(examples["InvestigationResultExample"]["value"])
    Investigation.model_validate(examples["InvestigationExample"]["value"])
