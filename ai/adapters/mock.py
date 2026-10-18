"""Deterministic mock adapter.

Default provider so the demo runs fully offline with predictable, review-safe
output and zero latency/cost. It exercises the exact same schemas and
validators as a live model, so the integration surface is real -- only the
generation is stubbed. Flip ``HKONTRANSIT_AI_PROVIDER`` to go live.
"""
from __future__ import annotations

import re

from ai.base import LLMAdapter


class MockAdapter(LLMAdapter):
    name = "mock"

    async def extract_intent(self, text: str, *, language: str | None = None) -> dict:
        t = (text or "").lower()
        prefs: list[dict] = []

        def _hit(*needles: str) -> bool:
            return any(n in t for n in needles)

        if _hit("\u5c11\u8d70\u8def", "less walk", "less walking", "minimal walking", "reduce walk", "\u4e0d\u60f3\u8d70", "\u5c11\u884c"):
            prefs.append({"key": "less_walking", "weight": 0.9,
                          "rationale": "Less walking requested."})
        if _hit("\u5c11\u6362\u4e58", "fewer transfer", "no transfer", "no changes", "\u4e0d\u6362", "\u5c11\u8f6c"):
            prefs.append({"key": "fewer_transfers", "weight": 0.8,
                          "rationale": "Fewer transfers requested."})
        if _hit("\u5feb", "faster", "fastest", "quick", "\u6700\u5feb", "\u5c3d\u5feb", "\u8d76\u65f6\u95f4"):
            prefs.append({"key": "faster", "weight": 0.85,
                          "rationale": "Faster arrival requested."})
        if _hit("\u4fbf\u5b9c", "cheap", "\u7701\u94b1", "\u4fbf\u5b9c\u70b9", "\u6700\u5e73"):
            prefs.append({"key": "cheaper", "weight": 0.7,
                          "rationale": "Lower cost requested."})
        if _hit("\u65e0\u969c\u788d", "accessib", "wheelchair", "\u8f6e\u6905", "\u8f6e\u6905", "\u8f6e\u6905", "step-free", "\u65e0\u9636"):
            prefs.append({"key": "accessible", "weight": 1.0,
                          "rationale": "Accessible travel requested."})
        if _hit("\u8d35\u4e00\u70b9\u4e5f", "even if it costs", "\u8d35\u90fd", "\u591a\u82b1\u70b9\u94b1"):
            # User explicitly sacrifices cost -> down-weight cheaper.
            prefs = [p for p in prefs if p["key"] != "cheaper"]
            prefs.append({"key": "cheaper", "weight": 0.2,
                          "rationale": "Higher cost is acceptable."})

        chips: list[str] = []
        if any(p["key"] == "faster" for p in prefs):
            chips.append("prefFast")
        if any(p["key"] == "less_walking" for p in prefs):
            chips.append("prefWalk")
        if any(p["key"] == "fewer_transfers" for p in prefs):
            chips.append("prefTransfer")

        lang = "zh-Hant" if re.search(r"[\u4e00-\u9fff]", text or "") else "en"

        return {
            "preferences": prefs,
            "language_detected": language or lang,
            "confidence": round(min(1.0, 0.4 + 0.2 * len(prefs)), 2) if prefs else 0.0,
            "suggested_chips": chips,
            "notes": "Local keyword interpretation (not a live AI model)." if prefs else "No clear preference detected.",
        }

    async def structure_report(self, text: str, *, context: dict | None = None) -> dict:
        ctx = context or {}
        t = (text or "").lower()
        if "\u672a\u505c" in t or "passed" in t or "\u6ca1\u505c" in t:
            etype, sev = "passed_without_stopping", "medium"
        elif "\u6ee1" in t or "full" in t or "\u4e0a\u4e0d\u4e86" in t:
            etype, sev = "suspected_full", "medium"
        elif "\u4e0a\u4e0d\u4e86\u8f66" in t or "unable" in t:
            etype, sev = "unable_to_board", "high"
        elif "\u5230\u7ad9" in t or "arrived" in t or "\u5230\u4e86" in t:
            etype, sev = "vehicle_arrived", "low"
        elif "\u4f4d\u7f6e" in t or "wrong stop" in t or "\u9519\u7ad9" in t:
            etype, sev = "wrong_stop_location", "medium"
        elif "\u65e0\u969c\u788d" in t or "accessib" in t or "\u8f6e\u6905" in t:
            etype, sev = "accessibility_obstacle", "high"
        elif "delay" in t or "\u5ef6\u8bef" in t or "\u665a\u70b9" in t:
            etype, sev = "delay", "medium"
        else:
            etype, sev = "other", "low"

        summaries = {
            "passed_without_stopping": "A vehicle was reported passing without stopping.",
            "suspected_full": "A vehicle was reported as possibly full.",
            "unable_to_board": "A passenger reported being unable to board.",
            "vehicle_arrived": "A vehicle arrival was reported.",
            "wrong_stop_location": "A possible incorrect stop location was reported.",
            "accessibility_obstacle": "An accessibility obstacle was reported.",
            "delay": "A possible service delay was reported.",
            "other": "A community observation was submitted for review.",
        }
        return {
            "event_type": etype,
            "operator": ctx.get("operator"),
            "route": ctx.get("route"),
            "direction": ctx.get("direction"),
            "stop_name": ctx.get("stop_name"),
            "occurred_at": None,
            "severity": sev,
            "summary": summaries[etype],
            "verification_status": "unverified",
            "language_detected": "zh-Hant" if re.search(r"[\u4e00-\u9fff]", text or "") else "en",
        }

    async def explain_route(self, route_data: dict, *, preferences: dict | None = None,
                            language: str = "en") -> dict:
        prefs = preferences or {}
        legs = route_data.get("legs") or route_data.get("segments") or []
        n_transfer = max(0, len(legs) - 1) if legs else 0
        walk_min = route_data.get("walk_minutes") or route_data.get("walk") or 0
        total_min = route_data.get("total_minutes") or route_data.get("duration_minutes") or 0
        mode = route_data.get("summary") or route_data.get("mode") or ""

        why: list[str] = []
        if prefs.get("less_walking") and walk_min:
            why.append("Less walking matches your preference.")
        if prefs.get("fewer_transfers"):
            why.append(f"Requires {n_transfer} transfers.")
        if prefs.get("faster") and total_min:
            why.append(f"Estimated duration: {total_min} minutes.")
        if not why:
            why.append("Balances duration, transfers and walking.")

        tradeoffs: list[str] = []
        if walk_min and not prefs.get("less_walking"):
            tradeoffs.append(f"About {walk_min} minutes of walking.")
        if n_transfer:
            tradeoffs.append(f"Requires {n_transfer} transfers.")

        zh = language.startswith("zh")
        return {
            "route_summary": mode if mode and not re.search(r"[\u3400-\u9fff]", str(mode)) else "Route overview",
            "why_recommended": why if zh else ["Recommended by the transport engine."],
            "trade_offs": tradeoffs,
            "walk_note": f"About {walk_min} minutes of walking." if walk_min else None,
            "fare_note": None,
            "accessibility_note": "Check accessibility separately." if zh else None,
            "confidence": 0.6,
        }
