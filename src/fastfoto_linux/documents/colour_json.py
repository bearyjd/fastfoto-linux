"""Strict, small colour fields of the versioned document review sidecar."""

from typing import Any

from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy


def encode_decision(decision: ColourDecision | None) -> dict[str, str] | None:
    if decision is None:
        return None
    return {
        "source_kind": decision.source_kind.value,
        "mode": decision.mode.value,
        "reason": decision.reason.value,
    }


def decode_decision(value: Any, version: int) -> ColourDecision | None:
    if value is None:
        return None
    if version == 1 or type(value) is not dict:
        raise ValueError("colour decisions need a version 2 object")
    return ColourDecision(
        ColourMode(value.get("source_kind")),
        ColourMode(value.get("mode")),
        ColourReason(value.get("reason")),
    )


def decode_policy(value: Any, version: int) -> ColourPolicy | None:
    if value is None:
        return None
    if version == 1 or type(value) is not str:
        raise ValueError("colour overrides need version 2 and a known mode")
    return ColourPolicy(value)
