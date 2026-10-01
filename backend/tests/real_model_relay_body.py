"""Bounded HTTP entity-body reader, including Spring's chunked synchronous calls."""

from __future__ import annotations

from typing import Protocol

LIMIT = 10 * 1024 * 1024


class BodyReader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...

    def readline(self, size: int = -1, /) -> bytes: ...


def request_body(stream: BodyReader, content_length: str | None, transfer_encoding: str | None) -> bytes:
    if transfer_encoding is not None:
        if transfer_encoding.casefold().strip() != "chunked" or content_length is not None:
            raise ValueError("Unsupported or ambiguous request framing")
        chunks: list[bytes] = []
        total = 0
        while True:
            line = stream.readline(8193)
            if len(line) > 8192 or not line.endswith(b"\r\n"):
                raise ValueError("Invalid chunk size framing")
            size = int(line.split(b";", 1)[0].strip(), 16)
            if size < 0 or total + size > LIMIT:
                raise ValueError("Acceptance body exceeds its limit")
            if size == 0:
                trailer_bytes = 0
                while (trailer := stream.readline(8193)) != b"\r\n":
                    trailer_bytes += len(trailer)
                    if not trailer or trailer_bytes > 8192 or not trailer.endswith(b"\r\n"):
                        raise ValueError("Invalid request trailers")
                return b"".join(chunks)
            chunk = stream.read(size)
            if len(chunk) != size or stream.read(2) != b"\r\n":
                raise ValueError("Incomplete chunked request")
            chunks.append(chunk)
            total += size
    if content_length is None:
        raise ValueError("Acceptance request has no entity-body framing")
    size = int(content_length)
    if size < 0 or size > LIMIT:
        raise ValueError("Acceptance body exceeds its limit")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Incomplete fixed-length request")
    return body
