"""Tests for the core result models in copilot_core.models (#11)."""

import ast
import copy
import hashlib
import json
import math
import pickle
from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from copilot_core.models import (
    AnomalyResult,
    BaselineResult,
    ComparisonEntry,
    ComparisonResult,
    Finding,
    Geography,
    Method,
    Parameters,
    Period,
    SeriesPoint,
    SeriesResult,
    SourceRef,
)

ROOT = Path(__file__).resolve().parents[1]


# --- Builders ---------------------------------------------------------------


def source(**overrides):
    data = {
        "id": "mart_inflation",
        "name": "Consumer price inflation",
        "provider": "IMF",
        "url": None,
        "last_updated": "2026-06-30",
    }
    return {**data, **overrides}


def method(**overrides):
    data = {
        "name": "z_score",
        "description": "Distance from the baseline mean in baseline standard deviations.",
        "parameters": {"baseline_periods": 4, "threshold": 2.0},
    }
    return {**data, **overrides}


def period(start="2022", end="2022", frequency="annual"):
    return {"start": start, "end": end, "frequency": frequency}


def geography(code="KEN", name="Kenya"):
    return {"country_code": code, "country_name": name}


def numeric(**overrides):
    data = {
        "value": 7.7,
        "unit": "percent",
        "period": period(),
        "geography": geography(),
        "method": method(),
        "source": source(),
        "caveats": [],
    }
    return {**data, **overrides}


def finding(**overrides):
    data = numeric(
        id="finding-1",
        kind="anomaly",
        metric="inflation_cpi",
        statement="Kenya's 2022 inflation of 7.7% is unusually high.",
        result_ids=["anomaly-1"],
    )
    return {**data, **overrides}


def series(**overrides):
    data = {
        "id": "series-1",
        "metric": "inflation_cpi",
        "unit": "percent",
        "period": period("2018", "2020"),
        "geography": geography(),
        "method": method(name="observed", description="Values as published.", parameters={}),
        "source": source(),
        "caveats": [],
        "points": [
            {"period": "2018", "value": 4.7},
            {"period": "2019", "value": 5.2},
            {"period": "2020", "value": 5.4},
        ],
    }
    return {**data, **overrides}


def comparison_entry(**overrides):
    return {**numeric(rank=1), **overrides}


def comparison(**overrides):
    data = {
        "id": "comparison-1",
        "metric": "inflation_cpi",
        "method": method(name="rank_by_value", description="Ranked by value.", parameters={}),
        "entries": [
            comparison_entry(value=18.8, rank=1, geography=geography("NGA", "Nigeria")),
            comparison_entry(value=7.7, rank=2),
        ],
    }
    return {**data, **overrides}


def baseline(**overrides):
    data = numeric(
        id="baseline-1",
        metric="inflation_cpi",
        baseline_value=5.35,
        baseline_period=period("2018", "2021"),
        difference=2.35,
        percent_difference=43.93,
    )
    return {**data, **overrides}


def anomaly(**overrides):
    data = numeric(
        id="anomaly-1",
        metric="inflation_cpi",
        is_anomaly=True,
        score=3.98,
        threshold=2,
        expected_value=5.35,
        direction="above",
    )
    return {**data, **overrides}


RESULT_BUILDERS = {
    Finding: finding,
    SeriesResult: series,
    ComparisonEntry: comparison_entry,
    ComparisonResult: comparison,
    BaselineResult: baseline,
    AnomalyResult: anomaly,
}

ALL_MODELS = {
    SourceRef: source,
    Geography: geography,
    Period: period,
    Method: method,
    SeriesPoint: lambda: {"period": "2022", "value": None},
    **RESULT_BUILDERS,
}


def error_locs(exc: ValidationError) -> list[str]:
    return [".".join(str(part) for part in err["loc"]) for err in exc.errors()]


# --- Valid results ----------------------------------------------------------


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__name__)
def test_valid_data_builds(model):
    assert isinstance(model.model_validate(ALL_MODELS[model]()), model)


def test_contract_example_values_build():
    """Values shaped like the InvestigationResultExample in api/openapi.yaml."""
    result = AnomalyResult.model_validate(anomaly())
    assert result.geography.country_code == "KEN"
    assert result.source.last_updated == date(2026, 6, 30)
    assert result.method.parameters == {"baseline_periods": 4, "threshold": 2.0}


# --- Every numeric result carries value, unit, period, geography, method,
# --- parameters and source --------------------------------------------------


@pytest.mark.parametrize(
    "model", [Finding, ComparisonEntry, BaselineResult, AnomalyResult], ids=lambda m: m.__name__
)
@pytest.mark.parametrize("field", ["value", "unit", "period", "geography", "method", "source"])
def test_numeric_results_require_citation_fields(model, field):
    data = RESULT_BUILDERS[model]()
    del data[field]
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    assert field in error_locs(exc.value)


@pytest.mark.parametrize("field", ["unit", "period", "geography", "method", "source", "points"])
def test_series_requires_citation_fields(field):
    data = series()
    del data[field]
    with pytest.raises(ValidationError) as exc:
        SeriesResult.model_validate(data)
    assert field in error_locs(exc.value)


def test_method_requires_parameters():
    data = method()
    del data["parameters"]
    with pytest.raises(ValidationError) as exc:
        Method.model_validate(data)
    assert error_locs(exc.value) == ["parameters"]


def test_comparison_entries_each_carry_their_own_citation():
    result = ComparisonResult.model_validate(comparison())
    nigeria = result.entries[0]
    assert (nigeria.value, nigeria.unit, nigeria.geography.country_code) == (18.8, "percent", "NGA")
    assert nigeria.source.id == "mart_inflation"


# --- SourceRef --------------------------------------------------------------


def test_source_ref_holds_model_provider_and_last_updated():
    ref = SourceRef.model_validate(source())
    assert ref.id == "mart_inflation"
    assert ref.provider == "IMF"
    assert ref.last_updated == date(2026, 6, 30)


def test_source_ref_allows_unknown_provider_url_and_date():
    ref = SourceRef.model_validate(source(provider=None, url=None, last_updated=None))
    assert ref.provider is None and ref.last_updated is None


def test_source_ref_accepts_url():
    ref = SourceRef.model_validate(source(url="https://www.imf.org/en/Data"))
    assert str(ref.url) == "https://www.imf.org/en/Data"


@pytest.mark.parametrize(
    "field, value",
    [("id", ""), ("name", " "), ("last_updated", "June 2026"), ("url", "not a url")],
)
def test_source_ref_rejects_invalid_fields(field, value):
    with pytest.raises(ValidationError) as exc:
        SourceRef.model_validate(source(**{field: value}))
    assert error_locs(exc.value)[0] == field


# --- Empty unit, empty method, no source ------------------------------------


@pytest.mark.parametrize("model", RESULT_BUILDERS, ids=lambda m: m.__name__)
def test_empty_method_name_is_rejected(model):
    data = RESULT_BUILDERS[model](method=method(name=""))
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    assert "method.name" in error_locs(exc.value)


@pytest.mark.parametrize(
    "model", [m for m in RESULT_BUILDERS if m is not ComparisonResult], ids=lambda m: m.__name__
)
@pytest.mark.parametrize("unit", ["", "   "])
def test_empty_unit_is_rejected(model, unit):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(RESULT_BUILDERS[model](unit=unit))
    assert "unit" in error_locs(exc.value)


@pytest.mark.parametrize(
    "model", [m for m in RESULT_BUILDERS if m is not ComparisonResult], ids=lambda m: m.__name__
)
def test_no_source_is_rejected(model):
    data = RESULT_BUILDERS[model]()
    data["source"] = None
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    assert "source" in error_locs(exc.value)


def test_comparison_entry_without_source_is_rejected():
    data = comparison()
    del data["entries"][1]["source"]
    with pytest.raises(ValidationError) as exc:
        ComparisonResult.model_validate(data)
    assert "entries.1.source" in error_locs(exc.value)


def test_empty_method_description_is_rejected():
    with pytest.raises(ValidationError) as exc:
        Method.model_validate(method(description=""))
    assert error_locs(exc.value) == ["description"]


# --- Geography --------------------------------------------------------------


@pytest.mark.parametrize("code", ["KEN", "NGA", "ZAF"])
def test_geography_accepts_alpha3(code):
    assert Geography.model_validate(geography(code)).country_code == code


@pytest.mark.parametrize("code", ["Kenya", "KE", "ken", "KENY", "", "K3N"])
def test_geography_rejects_non_alpha3(code):
    with pytest.raises(ValidationError) as exc:
        Geography.model_validate(geography(code))
    assert error_locs(exc.value) == ["country_code"]


def test_result_with_country_name_as_code_is_rejected():
    with pytest.raises(ValidationError) as exc:
        Finding.model_validate(finding(geography=geography("Kenya")))
    assert "geography.country_code" in error_locs(exc.value)


# --- Period -----------------------------------------------------------------


@pytest.mark.parametrize(
    "label, frequency",
    [("2023", "annual"), ("2023-Q1", "quarterly"), ("2023-01", "monthly"), ("2023-01-31", "daily")],
)
def test_period_accepts_each_format(label, frequency):
    result = Period.model_validate(period(label, label, frequency))
    assert result.start == result.end == label
    assert SeriesPoint.model_validate({"period": label, "value": 1.0}).period == label


@pytest.mark.parametrize(
    "label",
    [
        "23",
        "2023-Q5",
        "2023Q1",
        "2023-13",
        "2023-1",
        "2023-02-30",
        "2023-01-32",
        "2023/01",
        "Jan 2023",
        "2023-01-31T00:00",
        "",
    ],
)
def test_period_rejects_other_formats(label):
    with pytest.raises(ValidationError) as exc:
        SeriesPoint.model_validate({"period": label, "value": 1.0})
    assert error_locs(exc.value) == ["period"]


def test_period_labels_must_match_frequency():
    with pytest.raises(ValidationError, match="does not match frequency .quarterly."):
        Period.model_validate(period("2023", "2023-Q2", "quarterly"))


def test_period_start_must_not_be_after_end():
    with pytest.raises(ValidationError, match="after end"):
        Period.model_validate(period("2023", "2022"))


def test_period_rejects_unknown_frequency():
    with pytest.raises(ValidationError) as exc:
        Period.model_validate(period(frequency="weekly"))
    assert error_locs(exc.value) == ["frequency"]


def test_series_points_must_lie_within_period():
    data = series(points=[{"period": "2021", "value": 1.0}])
    with pytest.raises(ValidationError, match=r"points\.0\.period '2021'"):
        SeriesResult.model_validate(data)


def test_series_points_must_match_frequency():
    data = series(points=[{"period": "2019-01", "value": 1.0}])
    with pytest.raises(ValidationError, match="not a period of frequency .annual."):
        SeriesResult.model_validate(data)


# --- NaN, infinity and missing values ---------------------------------------


NON_FINITE = [math.nan, math.inf, -math.inf]


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize(
    "model", [Finding, ComparisonEntry, BaselineResult, AnomalyResult], ids=lambda m: m.__name__
)
def test_value_rejects_nan_and_infinity(model, bad):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(RESULT_BUILDERS[model](value=bad))
    assert "value" in error_locs(exc.value)


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize(
    "model, field",
    [
        (BaselineResult, "baseline_value"),
        (BaselineResult, "difference"),
        (BaselineResult, "percent_difference"),
        (AnomalyResult, "score"),
        (AnomalyResult, "threshold"),
        (AnomalyResult, "expected_value"),
    ],
)
def test_derived_numbers_reject_nan_and_infinity(model, field, bad):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(RESULT_BUILDERS[model](**{field: bad}))
    assert field in error_locs(exc.value)


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
def test_series_point_rejects_nan_and_infinity(bad):
    with pytest.raises(ValidationError) as exc:
        SeriesPoint.model_validate({"period": "2022", "value": bad})
    assert error_locs(exc.value) == ["value"]


@pytest.mark.parametrize("bad", [True, "7.7"])
def test_value_rejects_booleans_and_strings(bad):
    with pytest.raises(ValidationError):
        Finding.model_validate(finding(value=bad))


def test_integer_value_is_accepted_as_number():
    assert Finding.model_validate(finding(value=7)).value == 7


@pytest.mark.parametrize(
    "model", [Finding, ComparisonEntry, BaselineResult, AnomalyResult], ids=lambda m: m.__name__
)
def test_missing_value_without_caveat_is_rejected(model):
    data = RESULT_BUILDERS[model](value=None, caveats=[])
    if model is ComparisonEntry:
        data["rank"] = None
    with pytest.raises(ValidationError, match="caveats must explain why value is missing"):
        model.model_validate(data)


@pytest.mark.parametrize(
    "model", [Finding, ComparisonEntry, BaselineResult, AnomalyResult], ids=lambda m: m.__name__
)
def test_missing_value_with_caveat_is_accepted(model):
    data = RESULT_BUILDERS[model](value=None, caveats=["2022 is missing in the source."])
    if model is ComparisonEntry:
        data["rank"] = None
    assert model.model_validate(data).value is None


@pytest.mark.parametrize(
    "model, field",
    [
        (BaselineResult, "baseline_value"),
        (BaselineResult, "difference"),
        (BaselineResult, "percent_difference"),
        (AnomalyResult, "score"),
        (AnomalyResult, "expected_value"),
    ],
)
def test_missing_derived_number_requires_caveat(model, field):
    with pytest.raises(ValidationError, match=f"why {field} is missing"):
        model.model_validate(RESULT_BUILDERS[model](**{field: None}))
    data = RESULT_BUILDERS[model](**{field: None}, caveats=["Too few periods for a baseline."])
    assert getattr(model.model_validate(data), field) is None


def test_missing_series_point_requires_caveat():
    points = [{"period": "2018", "value": 4.7}, {"period": "2019", "value": None}]
    with pytest.raises(ValidationError, match="values for 2019 are missing"):
        SeriesResult.model_validate(series(points=points))
    result = SeriesResult.model_validate(series(points=points, caveats=["2019 is missing."]))
    assert result.points[1].value is None


@pytest.mark.parametrize("caveat", ["", "   "])
def test_blank_caveat_is_rejected(caveat):
    with pytest.raises(ValidationError) as exc:
        Finding.model_validate(finding(value=None, caveats=[caveat]))
    assert "caveats.0" in error_locs(exc.value)


def test_comparison_rank_must_be_null_when_value_missing():
    data = comparison_entry(value=None, rank=1, caveats=["Missing in the source."])
    with pytest.raises(ValidationError, match="rank must be null"):
        ComparisonEntry.model_validate(data)


def test_comparison_rank_starts_at_one():
    with pytest.raises(ValidationError) as exc:
        ComparisonEntry.model_validate(comparison_entry(rank=0))
    assert error_locs(exc.value) == ["rank"]


def test_anomaly_threshold_cannot_be_missing():
    with pytest.raises(ValidationError) as exc:
        AnomalyResult.model_validate(anomaly(threshold=None, caveats=["x"]))
    assert error_locs(exc.value) == ["threshold"]


# --- parameters -------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["z_score", 4, 2.5, True, False, [1, 2, 3], ["KEN", "NGA"], [True, 1.5, "x"], []],
)
def test_parameters_accept_json_scalars_and_lists(value):
    result = Method.model_validate(method(parameters={"p": value}))
    expected = tuple(value) if isinstance(value, list) else value
    assert result.parameters["p"] == expected
    assert json.loads(result.model_dump_json())["parameters"]["p"] == value


def test_parameters_keep_booleans_and_integers_distinct():
    result = Method.model_validate(method(parameters={"flag": True, "n": 1, "x": 1.0}))
    assert [type(v) for v in result.parameters.values()] == [bool, int, float]


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"nested": 1},
        [[1, 2]],
        [None],
        (1, 2),
        {1, 2},
        date(2022, 1, 1),
        b"bytes",
        object(),
        math.nan,
        math.inf,
        [math.nan],
    ],
    ids=repr,
)
def test_parameters_reject_other_values(value):
    with pytest.raises(ValidationError) as exc:
        Method.model_validate(method(parameters={"p": value}))
    assert all(loc.startswith("parameters.p") for loc in error_locs(exc.value))


# --- Round trip, JSON Schema and immutability --------------------------------


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__name__)
def test_round_trips_through_json(model):
    m = model.model_validate(ALL_MODELS[model]())
    assert model.model_validate_json(m.model_dump_json()) == m


def test_round_trip_keeps_missing_values_and_urls():
    m = SeriesResult.model_validate(
        series(
            points=[{"period": "2018", "value": None}],
            caveats=["2018 is missing."],
            source=source(url="https://www.imf.org/en/Data", last_updated=None),
        )
    )
    dumped = json.loads(m.model_dump_json())
    assert dumped["points"][0]["value"] is None
    assert SeriesResult.model_validate_json(m.model_dump_json()) == m


def test_round_trip_fails_for_unequal_models():
    a = Finding.model_validate(finding())
    b = Finding.model_validate(finding(value=7.8))
    assert Finding.model_validate_json(a.model_dump_json()) != b


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__name__)
def test_produces_json_schema(model):
    schema = model.model_json_schema()
    assert schema["type"] == "object"
    json.dumps(schema)


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__name__)
def test_models_are_frozen(model):
    m = model.model_validate(ALL_MODELS[model]())
    field = next(iter(model.model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(m, field, getattr(m, field))


def frozen_parameters_finding():
    return Finding.model_validate(
        finding(method=method(parameters={"a": [1, "x", True], "b": 1.5, "c": 3}))
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.__setitem__("b", 99.0),
        lambda p: p.__setitem__("bad", math.nan),
        lambda p: p.__setitem__("obj", {"nested": object()}),
        lambda p: p.__delitem__("b"),
        lambda p: p.update({"b": 99.0}),
        lambda p: p.pop("b"),
        lambda p: p.clear(),
        lambda p: p["a"].append("y"),
        lambda p: p["a"].__setitem__(0, 2),
        lambda p: setattr(p, "_items", {}),
        lambda p: p._items.__setitem__("b", 99.0),
    ],
    ids=[
        "set",
        "set-nan",
        "set-object",
        "delete",
        "update",
        "pop",
        "clear",
        "list-append",
        "list-set",
        "replace-store",
        "store-set",
    ],
)
def test_parameters_cannot_be_changed_in_place(change):
    f = frozen_parameters_finding()
    before = f.model_dump_json()
    with pytest.raises((TypeError, AttributeError)):
        change(f.method.parameters)
    assert f.model_dump_json() == before
    assert f.method.parameters == {"a": (1, "x", True), "b": 1.5, "c": 3}


def test_parameters_list_values_are_tuples_and_dump_as_lists():
    f = frozen_parameters_finding()
    assert f.method.parameters["a"] == (1, "x", True)
    assert f.model_dump()["method"]["parameters"] == {"a": [1, "x", True], "b": 1.5, "c": 3}
    assert json.loads(f.model_dump_json())["method"]["parameters"]["a"] == [1, "x", True]
    assert Finding.model_validate_json(f.model_dump_json()) == f
    assert Finding.model_validate(f.model_dump()) == f


def test_parameters_can_be_reused_in_another_method():
    f = frozen_parameters_finding()
    reused = Method(name="z_score", description="Reused.", parameters=f.method.parameters)
    assert reused.parameters == f.method.parameters


def test_parameters_still_reject_tuples_from_callers():
    with pytest.raises(ValidationError):
        Method.model_validate(method(parameters={"p": (1, 2)}))


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__name__)
def test_models_are_hashable(model):
    m = model.model_validate(ALL_MODELS[model]())
    copy = model.model_validate_json(m.model_dump_json())
    assert hash(m) == hash(copy)
    assert len({m, copy}) == 1


def test_hash_differs_when_parameters_differ():
    a = Method.model_validate(method(parameters={"p": [1, 2]}))
    b = Method.model_validate(method(parameters={"p": [1, 3]}))
    assert a != b and len({a, b}) == 2


def test_result_lists_are_immutable_tuples():
    result = SeriesResult.model_validate(series())
    assert isinstance(result.points, tuple) and isinstance(result.caveats, tuple)


@pytest.mark.parametrize("model", RESULT_BUILDERS, ids=lambda m: m.__name__)
def test_unknown_fields_are_rejected(model):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(RESULT_BUILDERS[model](colour="red"))
    assert error_locs(exc.value) == ["colour"]


# --- Deep copy and pickling (#69) -------------------------------------------

COPY_PARAMETERS = {"a": [1, "x", True], "b": 1.5, "c": 3, "d": "yoy", "e": False}
FROZEN_PARAMETERS = {"a": (1, "x", True), "b": 1.5, "c": 3, "d": "yoy", "e": False}


def with_parameters(builder, parameters):
    """The builder's data, with ``parameters`` in every Method it contains."""
    params = method(parameters=parameters)
    if builder is method:
        return params
    if builder is comparison:
        return comparison(
            method=params,
            entries=[
                comparison_entry(
                    value=18.8, rank=1, method=params, geography=geography("NGA", "Nigeria")
                ),
                comparison_entry(value=7.7, rank=2, method=params),
            ],
        )
    if builder in (finding, series, comparison_entry, baseline, anomaly):
        return builder(method=params)
    return builder()


# The six result models from #11, and Method on its own.
COPY_MODELS = {
    SourceRef: source,
    Finding: finding,
    SeriesResult: series,
    ComparisonResult: comparison,
    BaselineResult: baseline,
    AnomalyResult: anomaly,
    Method: method,
}

COPY_CASES = [
    pytest.param(model, params, id=f"{model.__name__}-{label}")
    for model in COPY_MODELS
    for label, params in (("params", COPY_PARAMETERS), ("empty", {}))
]


def build_for_copy(model, parameters):
    return model.model_validate(with_parameters(COPY_MODELS[model], parameters))


def methods_of(m):
    """Every Method inside a model, including those of comparison entries."""
    if isinstance(m, Method):
        return [m]
    found = [m.method] if hasattr(m, "method") else []
    found += [entry.method for entry in getattr(m, "entries", ())]
    return found


def pickle_round_trip(protocol):
    return lambda m: pickle.loads(pickle.dumps(m, protocol=protocol))


COPIERS = {
    "deepcopy": copy.deepcopy,
    "model_copy-deep": lambda m: m.model_copy(deep=True),
    **{
        f"pickle-{protocol}": pickle_round_trip(protocol)
        for protocol in range(2, pickle.HIGHEST_PROTOCOL + 1)
    },
}


def _ior(p):
    p |= {"b": 99.0}


PARAMETER_CHANGES = {
    "set": lambda p: p.__setitem__("b", 99.0),
    "delete": lambda p: p.__delitem__("b"),
    "update": lambda p: p.update({"b": 99.0}),
    "pop": lambda p: p.pop("b"),
    "clear": lambda p: p.clear(),
    "setdefault": lambda p: p.setdefault("z", 1),
    "ior": _ior,
    "list-append": lambda p: p["a"].append("y"),
    "replace-store": lambda p: setattr(p, "_items", {}),
    "delete-store": lambda p: delattr(p, "_items"),
    "store-set": lambda p: p._items.__setitem__("b", 99.0),
    "store-clear": lambda p: p._items.clear(),
    "new-attribute": lambda p: setattr(p, "extra", 1),
}


def assert_parameters_immutable(p):
    before = dict(p)
    for name, change in PARAMETER_CHANGES.items():
        if name == "list-append" and "a" not in p:
            continue
        with pytest.raises((TypeError, AttributeError, KeyError)):
            change(p)
    assert dict(p) == before
    if "a" in p:
        assert isinstance(p["a"], tuple)


def assert_model_immutable(m):
    before = m.model_dump_json()
    for inner in methods_of(m):
        with pytest.raises(ValidationError, match="frozen"):
            inner.parameters = {}
        assert_parameters_immutable(inner.parameters)
    assert m.model_dump_json() == before


@pytest.mark.parametrize("copier", COPIERS)
@pytest.mark.parametrize("model, parameters", COPY_CASES)
def test_models_deep_copy_and_pickle(model, parameters, copier):
    m = build_for_copy(model, parameters)
    original_json = m.model_dump_json()
    result = COPIERS[copier](m)

    assert type(result) is model
    assert result == m
    assert hash(result) == hash(m)
    assert result.model_dump_json() == original_json
    for inner in methods_of(result):
        assert isinstance(inner.parameters, Parameters)
        assert inner.parameters == {k: FROZEN_PARAMETERS[k] for k in parameters}
        if "a" in parameters:
            assert inner.parameters["a"] == (1, "x", True)

    assert_model_immutable(result)
    assert_model_immutable(m)
    assert m.model_dump_json() == original_json


@pytest.mark.parametrize("model, parameters", COPY_CASES)
def test_shallow_copy_and_model_copy_update_still_work(model, parameters):
    m = build_for_copy(model, parameters)
    shallow = copy.copy(m)
    assert shallow == m and hash(shallow) == hash(m)
    field = next(iter(model.model_fields))
    updated = m.model_copy(update={field: getattr(m, field)})
    assert updated == m and hash(updated) == hash(m)
    assert_model_immutable(shallow)
    assert_model_immutable(updated)


PARAMETER_COPIERS = {k: v for k, v in COPIERS.items() if k != "model_copy-deep"}


@pytest.mark.parametrize("copier", PARAMETER_COPIERS)
@pytest.mark.parametrize("parameters", [COPY_PARAMETERS, {}], ids=["params", "empty"])
def test_parameters_alone_deep_copy_and_pickle(parameters, copier):
    p = Method.model_validate(method(parameters=parameters)).parameters
    result = PARAMETER_COPIERS[copier](p)
    assert type(result) is Parameters
    assert result == p and hash(result) == hash(p)
    assert dict(result) == {k: FROZEN_PARAMETERS[k] for k in parameters}
    assert_parameters_immutable(result)
    assert_parameters_immutable(p)


def test_changing_a_copy_leaves_the_original_unchanged():
    m = build_for_copy(Finding, COPY_PARAMETERS)
    before = m.model_dump_json()
    for copier in COPIERS.values():
        result = copier(m)
        for change in PARAMETER_CHANGES.values():
            with pytest.raises((TypeError, AttributeError, KeyError)):
                change(result.method.parameters)
        with pytest.raises(ValidationError, match="frozen"):
            result.method.parameters = {}
        assert result.model_dump_json() == before
    assert m.model_dump_json() == before


class _CraftedParameters:
    """Pickles as a Parameters made with ``object.__new__``, skipping
    ``__init__``, with a plain mutable dict as its store."""

    def __reduce__(self):
        return (object.__new__, (Parameters,), (None, {"_items": {"b": 1.5}}))


def test_unpickling_cannot_give_mutable_parameters():
    p = Method.model_validate(method(parameters=COPY_PARAMETERS)).parameters
    # A real Parameters pickles as a call to Parameters(dict), with no state,
    # so unpickling always goes through __init__ and freezes the store.
    reduced = p.__reduce_ex__(pickle.HIGHEST_PROTOCOL)
    assert reduced[0] is Parameters and len(reduced) == 2
    # A crafted pickle that tries to set the store directly is refused.
    with pytest.raises(AttributeError):
        pickle.loads(pickle.dumps(_CraftedParameters()))
    # Unpickling a list value gives a tuple, not a list.
    data = pickle.dumps(Parameters({"a": [1, 2]}))
    assert pickle.loads(data)["a"] == (1, 2)
    assert_parameters_immutable(pickle.loads(pickle.dumps(p)))


def test_hashing_still_holds_for_copies():
    a = build_for_copy(Finding, COPY_PARAMETERS)
    b = build_for_copy(Finding, {**COPY_PARAMETERS, "c": 4})
    copies = [copier(a) for copier in COPIERS.values()]
    assert a != b
    assert len({a, b, *copies}) == 2
    assert all(c != b and hash(c) == hash(a) for c in copies)


def test_parameters_reject_non_string_keys():
    with pytest.raises(ValidationError):
        Method.model_validate(method(parameters={1: "x"}))


def test_parameters_from_a_copy_can_be_reused_in_another_method():
    m = pickle.loads(pickle.dumps(build_for_copy(Finding, COPY_PARAMETERS)))
    reused = Method(name="z_score", description="Reused.", parameters=m.method.parameters)
    assert reused.parameters == FROZEN_PARAMETERS
    with pytest.raises(ValidationError):
        Method.model_validate(method(parameters={"p": (1, 2)}))


def contract_digest():
    """A digest of model_dump(), model_dump_json() and model_json_schema() in
    validation and serialization mode, for every model."""
    parts = []
    for model in ALL_MODELS:
        m = model.model_validate(with_parameters(ALL_MODELS[model], COPY_PARAMETERS))
        parts.append(m.model_dump_json())
        parts.append(repr(m.model_dump()))
        for mode in ("validation", "serialization"):
            parts.append(json.dumps(model.model_json_schema(mode=mode), sort_keys=True))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# contract_digest() computed with copilot_core/models.py at b086c7b.
CONTRACT_DIGEST_AT_B086C7B = "96f449bd4747e1fc89581ab06681b8e132106f85c53ea8c19fc24e9a40ff3f2e"


def test_dumps_and_schemas_are_unchanged_since_b086c7b():
    assert contract_digest() == CONTRACT_DIGEST_AT_B086C7B


# --- Match the contract ------------------------------------------------------

# Field names and required fields of the schemas in api/openapi.yaml, with
# allOf expanded. The automated contract check is #57; this pins the models.
CONTRACT = {
    SourceRef: ("Source", {"id", "name", "provider", "url", "last_updated"}),
    Geography: ("Geography", {"country_code", "country_name"}),
    Period: ("Period", {"start", "end", "frequency"}),
    Method: ("Method", {"name", "description", "parameters"}),
    SeriesPoint: ("SeriesPoint", {"period", "value"}),
    Finding: (
        "Finding",
        {"value", "unit", "period", "geography", "method", "source", "caveats"}
        | {"id", "kind", "metric", "statement", "result_ids"},
    ),
    SeriesResult: (
        "Series",
        {"id", "metric", "unit", "period", "geography", "method", "source", "caveats", "points"},
    ),
    ComparisonEntry: (
        "ComparisonEntry",
        {"value", "unit", "period", "geography", "method", "source", "caveats", "rank"},
    ),
    ComparisonResult: ("ComparisonResult", {"id", "metric", "method", "entries"}),
    BaselineResult: (
        "BaselineResult",
        {"value", "unit", "period", "geography", "method", "source", "caveats"}
        | {"id", "metric", "baseline_value", "baseline_period", "difference"}
        | {"percent_difference"},
    ),
    AnomalyResult: (
        "AnomalyResult",
        {"value", "unit", "period", "geography", "method", "source", "caveats"}
        | {"id", "metric", "is_anomaly", "score", "threshold", "expected_value", "direction"},
    ),
}


@pytest.mark.parametrize("model", CONTRACT, ids=lambda m: m.__name__)
def test_fields_match_contract(model):
    title, fields = CONTRACT[model]
    schema = model.model_json_schema()
    assert schema["title"] == title
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields


def test_contract_names_every_schema_the_models_implement():
    contract = (ROOT / "api" / "openapi.yaml").read_text(encoding="utf-8")
    for title, _ in CONTRACT.values():
        assert f"\n    {title}:\n" in contract


def test_contract_period_label_accepts_daily_dates():
    contract = (ROOT / "api" / "openapi.yaml").read_text(encoding="utf-8")
    assert "enum: [annual, quarterly, monthly, daily]" in contract
    assert '(-(0[1-9]|[12][0-9]|3[01]))?)?$"' in contract


@pytest.mark.parametrize(
    "model, field, values",
    [
        (Finding, "kind", ["trend", "comparison", "baseline", "anomaly", "data_gap"]),
        (AnomalyResult, "direction", ["above", "below", None]),
        (Period, "frequency", ["annual", "quarterly", "monthly", "daily"]),
    ],
)
def test_enums_match_contract(model, field, values):
    schema = json.dumps(model.model_json_schema())
    for value in values:
        if value is not None:
            assert f'"{value}"' in schema


# --- No web framework in copilot_core ----------------------------------------


def test_models_import_no_web_framework():
    tree = ast.parse((ROOT / "copilot_core" / "models.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"fastapi", "starlette", "flask", "django"}


def test_models_are_pydantic():
    for model in ALL_MODELS:
        assert issubclass(model, BaseModel)
