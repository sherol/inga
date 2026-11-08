"""Report schema: fields, defaults, normalization and validation."""

from __future__ import annotations

import datetime as dt
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from typing import Any

REPORT_TYPES = ("research", "review", "summary", "status", "analysis", "other")
STATUSES = ("unread", "read", "archived")
REQUIRED = ("date", "name", "project")

# Canonical order of frontmatter keys when a file is written.
FIELD_ORDER = (
    "id",
    "date",
    "name",
    "project",
    "author",
    "type",
    "summary",
    "tags",
    "source",
    "related",
    "star",
    "reading_list",
    "status",
    "read_at",
    "rating",
    "notes",
)

# Fields only a human (via the CLI) should change; agents leave them alone.
CURATION_FIELDS = ("star", "reading_list", "status", "read_at", "rating", "notes")


class ValidationError(ValueError):
    pass


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "report"


def new_id(date: str | None = None) -> str:
    day = (date or today())[:10].replace("-", "")
    return f"{day}-{secrets.token_hex(3)}"


def today() -> str:
    return dt.date.today().isoformat()


def now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def normalize_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string (date or datetime) or None."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    try:
        if len(text) == 10:
            return dt.date.fromisoformat(text).isoformat()
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(microsecond=0).isoformat()
    except ValueError as exc:
        raise ValidationError(f"not an ISO date/datetime: {value!r}") from exc


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    raise ValidationError(f"expected a list, got {value!r}")


def _as_bool(value: Any, name: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "yes", "1"):
        return True
    if isinstance(value, str) and value.lower() in ("false", "no", "0", ""):
        return False
    raise ValidationError(f"{name} must be true/false, got {value!r}")


@dataclass
class Report:
    id: str
    date: str
    name: str
    project: str
    author: str | None = None
    type: str = "other"
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    related: list[str] = field(default_factory=list)
    star: bool = False
    reading_list: bool = False
    status: str = "unread"
    read_at: str | None = None
    rating: int | None = None
    notes: str | None = None
    # Unknown frontmatter keys are kept so nothing an agent wrote is lost.
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> "Report":
        """Build a Report from raw frontmatter, normalizing and validating."""
        meta = dict(meta)
        missing = [k for k in REQUIRED if meta.get(k) in (None, "")]
        if missing:
            raise ValidationError(f"missing required field(s): {', '.join(missing)}")
        if not meta.get("id"):
            raise ValidationError("missing id")

        rtype = str(meta.get("type") or "other").lower()
        if rtype not in REPORT_TYPES:
            raise ValidationError(f"type must be one of {', '.join(REPORT_TYPES)}, got {rtype!r}")
        status = str(meta.get("status") or "unread").lower()
        if status not in STATUSES:
            raise ValidationError(f"status must be one of {', '.join(STATUSES)}, got {status!r}")

        rating = meta.get("rating")
        if rating in (None, ""):
            rating = None
        else:
            try:
                rating = int(rating)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"rating must be an integer 1-5, got {rating!r}") from exc
            if not 1 <= rating <= 5:
                raise ValidationError(f"rating must be 1-5, got {rating}")

        def opt_str(key: str) -> str | None:
            v = meta.get(key)
            return None if v in (None, "") else str(v)

        known = set(FIELD_ORDER)
        return cls(
            id=str(meta["id"]),
            date=normalize_timestamp(meta["date"]),
            name=str(meta["name"]),
            project=slugify(str(meta["project"])),
            author=opt_str("author"),
            type=rtype,
            summary=opt_str("summary"),
            tags=[t.lower() for t in _as_list(meta.get("tags"))],
            source=opt_str("source"),
            related=_as_list(meta.get("related")),
            star=_as_bool(meta.get("star"), "star"),
            reading_list=_as_bool(meta.get("reading_list"), "reading_list"),
            status=status,
            read_at=normalize_timestamp(meta.get("read_at")),
            rating=rating,
            notes=opt_str("notes"),
            extra={k: v for k, v in meta.items() if k not in known},
        )

    def to_meta(self) -> dict[str, Any]:
        """Frontmatter dict in canonical order. Empty optional fields are omitted."""
        out: dict[str, Any] = {}
        for key in FIELD_ORDER:
            value = getattr(self, key)
            if key in ("star", "reading_list"):
                out[key] = bool(value)
            elif key == "status":
                out[key] = value
            elif value in (None, "", []):
                continue
            else:
                out[key] = value
        out.update(self.extra)
        return out
