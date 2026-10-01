"""Driver diagnostics preserve failures without publishing credentials."""

from urllib.parse import quote, quote_plus

import pytest
from pymongo.errors import OperationFailure
from test_mongodb_adapter import command, config, fake_client
from test_mongodb_metadata import target

from app.adapters.diagnostics import sanitize_diagnostic
from app.adapters.document import render_document
from app.adapters.mongodb import MongoDbAdapter

PASSWORD = "synthetic p@:/+?#word"


def diagnostic(encoding: str, uri: bool) -> tuple[str, str]:
    secret = {"raw": PASSWORD, "quote": quote(PASSWORD, safe=""),
              "plus": quote_plus(PASSWORD)}[encoding]
    detail = f"mongodb://private-user:{secret}@localhost:17017/sample" if uri else secret
    return f"synthetic unavailable {detail}", secret


@pytest.mark.parametrize("encoding", ("raw", "quote", "plus"))
@pytest.mark.parametrize("uri", (False, True))
@pytest.mark.parametrize("component", ("collections", "fields", "indexes", "rowCount"))
def test_metadata_components_and_rendered_document_never_publish_secrets(
    monkeypatch: pytest.MonkeyPatch, encoding: str, uri: bool, component: str,
) -> None:
    adapter, collection = target(monkeypatch)
    message, secret = diagnostic(encoding, uri)
    failure = OperationFailure(message, code=13)
    if component == "collections":
        client = fake_client(monkeypatch, adapter)
        client["sample"].list_collection_names.side_effect = failure
    else:
        operation = {"fields": collection.find, "indexes": collection.list_indexes,
                     "rowCount": collection.estimated_document_count}[component]
        operation.side_effect = failure
    metadata = adapter.extract_metadata(config(username="private-user", password=PASSWORD))
    assert metadata["incomplete"] is True and isinstance(metadata["errorMessage"], str)
    for text in (metadata["errorMessage"], render_document(metadata)):
        assert secret not in text and PASSWORD not in text
        assert "synthetic unavailable" in text and "[REDACTED]" in text
        if uri:
            assert "private-user" not in text and "mongodb://[REDACTED]@localhost:17017/sample" in text
    if component != "collections":
        table = metadata["tables"][0]
        assert f"items {component}: OperationFailure" in metadata["errorMessage"]
        assert bool(table["columns"]) is (component != "fields")
        assert bool(table["indexes"]) is (component != "indexes")
        assert table["rowCount"] == (None if component == "rowCount" else 125)


@pytest.mark.parametrize("encoding", ("raw", "quote", "plus"))
@pytest.mark.parametrize("uri", (False, True))
def test_repairable_read_error_returns_only_sanitized_diagnostic(
    monkeypatch: pytest.MonkeyPatch, encoding: str, uri: bool,
) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    message, secret = diagnostic(encoding, uri)
    client["sample"]["items"].count_documents.side_effect = OperationFailure(
        "full response omitted", code=2, details={"errmsg": message, "private": PASSWORD},
    )
    result = adapter.execute(config(username="private-user", password=PASSWORD), command("count"))
    assert result["success"] is False and result["errorCode"] == 2
    assert secret not in result["error"] and PASSWORD not in result["error"]
    assert "synthetic unavailable" in result["error"] and "[REDACTED]" in result["error"]
    if uri:
        assert "private-user" not in result["error"]
    client["sample"]["items"].count_documents.assert_called_once()


@pytest.mark.parametrize("scheme", ("mongodb", "mongodb+srv", "MONGODB"))
def test_uri_credentials_are_removed_without_known_password(scheme: str) -> None:
    message = f"unavailable {scheme}://unknown-user:unknown%2Fpassword@host/sample"
    assert sanitize_diagnostic(message, config()) == f"unavailable {scheme}://[REDACTED]@host/sample"


def test_diagnostic_retains_safe_error_and_rejects_invalid_type() -> None:
    assert sanitize_diagnostic("items indexes entry 2: invalid name", config()) == (
        "items indexes entry 2: invalid name"
    )
    with pytest.raises(TypeError, match="diagnostic must be text"):
        sanitize_diagnostic(None, config())  # type: ignore[arg-type]
