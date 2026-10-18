"""Structured-output schemas for the GenAI interpretation/explanation layer.

Every LLM call MUST produce one of these Pydantic-validated structures. Raw
model output is never surfaced to the user directly; it is validated here, then
checked against transport-specific rules (see ``validators``) before use.

These schemas are the durable, model-agnostic contract the technical team
identified as the product's core value.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --- 1. Natural-language intent extraction ---------------------------------

class PreferenceKey(str, Enum):
    """Normalised travel-preference dimensions.

    These map onto the existing chip-based preference UI (prefFast /
    prefWalk / prefTransfer) plus v2 extensions. Keeping them a closed enum
    lets deterministic code branch on them safely instead of free-text.
    """
    FASTER = "faster"               # minimise total travel time
    FEWER_TRANSFERS = "fewer_transfers"
    LESS_WALKING = "less_walking"
    CHEAPER = "cheaper"             # cost-sensitive
    ACCESSIBLE = "accessible"       # barrier-free / step-free
    LESS_CROWDED = "less_crowded"   # comfort
    SCENIC = "scenic"               # low priority, but possible
    RELIABLE = "reliable"           # prefer on-time / stable services


class TravelPreference(BaseModel):
    """A single weighted preference extracted from the user's free text."""
    key: PreferenceKey
    weight: float = Field(
        ..., ge=0.0, le=1.0,
        description="0 = nice-to-have, 1 = hard requirement.",
    )
    rationale: str | None = Field(
        None, description="Short passenger-friendly reason, for transparency.",
    )


class InterpretedIntent(BaseModel):
    """Result of interpreting a natural-language journey request.

    Example input: "I want less walking, even if it costs more" ->
        preferences: [less_walking@0.9, cheaper@0.3 (down-weighted)],
        suggested_chips: ["prefWalk"]
    """
    preferences: list[TravelPreference] = Field(default_factory=list)
    language_detected: str = Field("und", description="BCP-47-ish tag, e.g. zh-Hant, en, und.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    raw_text: str
    suggested_chips: list[str] = Field(
        default_factory=list,
        description="IDs of the existing UI chips to activate (prefFast/prefWalk/prefTransfer).",
    )
    notes: str | None = None

    class Config:
        use_enum_values = True


# --- 2. Community report -> structured mobility event ----------------------

class ReportType(str, Enum):
    """Normalised community-report taxonomy.

    Mirrors the existing ``eventType`` <option> values in index.html so the LLM
    output drops straight into the existing verification queue.
    """
    PASSED_WITHOUT_STOPPING = "passed_without_stopping"
    SUSPECTED_FULL = "suspected_full"
    UNABLE_TO_BOARD = "unable_to_board"
    VEHICLE_ARRIVED = "vehicle_arrived"
    WRONG_STOP_LOCATION = "wrong_stop_location"
    ACCESSIBILITY_OBSTACLE = "accessibility_obstacle"
    DELAY = "delay"
    OTHER = "other"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MobilityEvent(BaseModel):
    """A free-text community observation converted into a standardised event.

    Uncertain community information stays explicitly ``unverified``; it never
    becomes transport fact until corroborated against official data and other
    independent reports (see the verification workflow in index.html).
    """
    event_type: ReportType
    operator: str | None = None
    route: str | None = None
    direction: str | None = None
    stop_name: str | None = None
    occurred_at: str | None = Field(
        None, description="ISO 8601 of when the event happened (not submit time).",
    )
    severity: Severity = Severity.LOW
    summary: str = Field(..., description="One-sentence passenger-friendly summary.")
    verification_status: Literal["unverified", "corroborated", "operator_confirmed"] = "unverified"
    raw_text: str
    language_detected: str = "und"

    class Config:
        use_enum_values = True


# --- 3. Route recommendation explanation ----------------------------------

class RouteExplanation(BaseModel):
    """Passenger-friendly explanation of a route recommendation.

    The LLM explains *why* a route fits the user's stated preferences; it does
    not invent ETA, fares or stop coordinates -- those come from official
    sources and are injected as context. The explanation is grounded.
    """
    route_summary: str
    why_recommended: list[str] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    walk_note: str | None = None
    fare_note: str | None = None
    accessibility_note: str | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)


# --- Request envelopes (API I/O contract) ---------------------------------

class InterpretRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    context: dict | None = Field(None, description="Optional context, e.g. current screen.")


class StructureReportRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    context: dict | None = Field(
        None, description="Optional known operator/route/stop to anchor extraction.",
    )


class ExplainRouteRequest(BaseModel):
    route_data: dict = Field(..., description="Deterministic route payload from the transport engine.")
    preferences: dict | None = None
    language: str = Field("en", description="Output language.")
