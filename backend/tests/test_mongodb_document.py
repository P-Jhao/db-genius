"""Inferred and incomplete metadata retain distinct, explicit document evidence."""

from typing import cast

import pytest

from app.adapters.document import render_document
from app.adapters.types import SchemaMetadata


def metadata(**overrides: object) -> SchemaMetadata:
    value: dict[str, object] = {"dbType": "mongodb", "databaseName": "empty", "host": "localhost",
                               "port": 27017, "tables": [], "incomplete": False,
                               "errorMessage": None, "schemaInferred": True, "sampleSize": 50}
    return cast(SchemaMetadata, {**value, **overrides})


def test_empty_sampled_database_has_warning_even_with_no_collections() -> None:
    document = render_document(metadata())
    assert "at most 50 sample documents per collection" in document
    assert "first-seen BSON types" in document
    assert "estimated row counts" in document and "not a complete formal schema" in document
    assert "manual review" in document and "Error reading metadata" not in document


@pytest.mark.parametrize("error", (None, "", "indexes unavailable"))
def test_partial_warning_keeps_error_or_explicit_unknown(error: str | None) -> None:
    document = render_document(metadata(incomplete=True, errorMessage=error))
    expected = "Unknown metadata error" if error is None or error == "" else error
    assert "Error reading metadata" in document and expected in document
    assert "Inferred schema" in document


@pytest.mark.parametrize("overrides", ({"schemaInferred": 1}, {"sampleSize": True}, {"sampleSize": 0},
                                       {"sampleSize": None}, {"incomplete": "false"},
                                       {"incomplete": True, "errorMessage": 0}))
def test_bad_warning_types_fail_explicitly(overrides: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        render_document(metadata(**overrides))


def test_missing_sample_size_for_inferred_schema_is_an_error() -> None:
    schema = metadata()
    del schema["sampleSize"]
    with pytest.raises(ValueError, match="sampleSize"):
        render_document(schema)
