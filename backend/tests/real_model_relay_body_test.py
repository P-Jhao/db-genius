"""Reject ambiguous and malformed request framing without dumping request bytes."""

from __future__ import annotations

from io import BytesIO

import pytest
from real_model_relay_body import request_body


@pytest.mark.parametrize("wire,content_length,transfer_encoding", [
    (b"", "0", "chunked"),
    (b"1\r\naX\n0\r\n\r\n", None, "chunked"),
    (b"1\r\na\r\n0\r\n", None, "chunked"),
    (b"short", "8", None),
    (b"", "-1", None),
    (b"", None, "gzip, chunked"),
])
def test_invalid_entity_body_is_an_explicit_error(wire: bytes, content_length: str | None,
                                                 transfer_encoding: str | None) -> None:
    with pytest.raises(ValueError):
        request_body(BytesIO(wire), content_length, transfer_encoding)
