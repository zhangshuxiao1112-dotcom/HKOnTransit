"""Deterministic validation layer between raw LLM output and product use.

The technical team's hybrid architecture requires that every GenAI result be
checked against schemas AND transport-specific rules before it is acted upon.
This module is the rule half (the schema half lives in ``schemas``).

It is intentionally conservative: when in doubt, it drops a field to null or
downgrades confidence rather than letting an unverified claim through.
"""
from __future__ import annotations

import re
from typing import Any

from ai.schemas import (
    InterpretedIntent,
    MobilityEvent,
    ReportType,
    RouteExplanation,
    TravelPreference,
)

# Recognised UI chip ids (kept in sync with index.html).
VALID_CHIPS = {"prefFast", "prefWalk", "prefTransfer"}
# Rough sanity ceiling so a hallucinated huge weight can't dominate routing.
_MAX_PREFERENCES = 6

# HK operator tokens we accept in structured reports (loose match, not authoritative).
_OPERATOR_HINTS = ("GMB", "KMB", "CTB", "MTR", "LWB", "NLB")


def _coerce_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _clean_str(value: Any, *, max_len: int = 280) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]


def validate_intent(raw: dict, *, source_text: str) -> InterpretedIntent:
    """Validate + clamp a raw intent dict into a safe :class:`InterpretedIntent`."""
    prefs: list[TravelPreference] = []
    for item in (raw.get("preferences") or [])[:_MAX_PREFERENCES]:
        if not isinstance(item, dict):
            continue
        try:
            pref = TravelPreference(
                key=item.get("key"),
                weight=_coerce_float(item.get("weight"), 0.5, 0.0, 1.0),
                rationale=_clean_str(item.get("rationale")),
            )
        except Exception:  # pydantic ValidationError on bad enum
            continue
        prefs.append(pref)

    chips = [c for c in (raw.get("suggested_chips") or []) if c in VALID_CHIPS]

    confidence = _coerce_float(raw.get("confidence"), 0.5 if prefs else 0.0, 0.0, 1.0)
    if not prefs:  # no interpretable preferences -> confidence must read as 0
        confidence = 0.0

    return InterpretedIntent(
        preferences=prefs,
        language_detected=_clean_str(raw.get("language_detected"), max_len=16) or "und",
        confidence=confidence,
        raw_text=(source_text or "")[:1000],
        suggested_chips=chips,
        notes=_clean_str(raw.get("notes")),
    )


def validate_report(raw: dict, *, source_text: str) -> MobilityEvent:
    """Validate a raw mobility-event dict. Unknown types fall back to ``other``.

    Everything produced here is forced to ``unverified``: the model is never
    trusted to grant corroboration. That is a deterministic-workflow decision.
    """
    event_type = raw.get("event_type")
    try:
        ReportType(event_type)  # validate enum membership
    except Exception:
        event_type = ReportType.OTHER

    return MobilityEvent(
        event_type=event_type,
        operator=_clean_str(raw.get("operator"), max_len=16),
        route=_clean_str(raw.get("route"), max_len=24),
        direction=_clean_str(raw.get("direction"), max_len=24),
        stop_name=_clean_str(raw.get("stop_name"), max_len=80),
        occurred_at=_iso_or_none(raw.get("occurred_at")),
        severity=raw.get("severity") if raw.get("severity") in ("low", "medium", "high") else "low",
        summary=_clean_str(raw.get("summary"), max_len=200) or (source_text or "")[:200],
        verification_status="unverified",
        raw_text=(source_text or "")[:2000],
        language_detected=_clean_str(raw.get("language_detected"), max_len=16) or "und",
    )


def validate_explanation(raw: dict) -> RouteExplanation:
    """Validate a raw explanation dict, clamping lists and confidence."""
    def _list(field: str, limit: int = 4) -> list[str]:
        out: list[str] = []
        for v in (raw.get(field) or [])[:limit]:
            s = _clean_str(v)
            if s:
                out.append(s)
        return out

    return RouteExplanation(
        route_summary=_clean_str(raw.get("route_summary"), max_len=160) or "",
        why_recommended=_list("why_recommended"),
        trade_offs=_list("trade_offs"),
        walk_note=_clean_str(raw.get("walk_note")),
        fare_note=_clean_str(raw.get("fare_note")),
        accessibility_note=_clean_str(raw.get("accessibility_note")),
        confidence=_coerce_float(raw.get("confidence"), 0.5, 0.0, 1.0),
    )


def looks_like_operator(token: str | None) -> bool:
    """Cheap deterministic check used to flag obviously-wrong operator guesses."""
    if not token:
        return False
    t = token.strip().upper()
    return any(h in t for h in _OPERATOR_HINTS)


# --- helpers --------------------------------------------------------------

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _iso_or_none(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    return s if _ISO_RE.match(s) else None
