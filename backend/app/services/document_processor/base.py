"""Source and storage abstractions for the document processor.

The processor never touches disk on its own: it consumes a `DocumentSource`
(in-memory bytes + metadata) and may optionally hand the same bytes to a
`DocumentStorage` implementation. The default `NoOpStorage` discards them,
which is what we want for the profile-extraction flow today. Plugging in
`LocalDiskStorage` or an S3 backend later only requires implementing the
protocol — the processor stays unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ProcessorError(RuntimeError):
    """Raised when document parsing fails in a user-actionable way."""


# Mime types Gemini natively understands as documents/images.
SUPPORTED_MIME_TYPES = frozenset({
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
    "text/plain",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
})

# Inline base64 ceiling. Raised to 19 MB so files up to 20 MB (our hard cap) never
# trigger the File API path — all uploads stay in-memory and in our own ChromaDB.
INLINE_LIMIT_BYTES = 19 * 1024 * 1024


@dataclass(frozen=True)
class DocumentSource:
    """A single document the user dropped into the app, in memory only."""

    filename: str
    mime_type: str
    data: bytes
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.data:
            raise ProcessorError("empty document")
        if self.mime_type not in SUPPORTED_MIME_TYPES:
            raise ProcessorError(f"unsupported mime type: {self.mime_type}")

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def needs_file_api(self) -> bool:
        return self.size_bytes > INLINE_LIMIT_BYTES


@runtime_checkable
class DocumentStorage(Protocol):
    """Optional persistence hook. Default implementation is a no-op."""

    def persist(self, source: DocumentSource) -> str | None:
        """Return a storage key/URI, or None if discarded."""
        ...


class NoOpStorage:
    """Drops the bytes — used during profile extraction where we don't keep files."""

    def persist(self, source: DocumentSource) -> str | None:
        return None
