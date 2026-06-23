"""Base types for v2 strategy + narration.

Slot kinds:
  LITERAL   — value is set by the strategy; narrator copies it.
  CHOICE    — narrator picks one option from a small list (random or hash-keyed).
  KSTORE    — value computed from a kstore query; narrator runs the callable.
  MODEL     — narrator calls the 1.5B with a tight prompt + validates against
              SlotConstraint. This is the ONLY place the model runs in v2.

Strategy contract:
  matches(perception, kstore) -> bool                — does this strategy apply?
  plan(perception, kstore)    -> ResponsePlan        — build the slotted plan
  priority                                           — int; higher wins ties

ResponsePlan carries:
  - strategy_name (for tracing + reviewer)
  - template (Python str.format; slot names as {placeholders})
  - slots (tuple, evaluated in order)
  - expected_shape (e.g. "two_beat", "recall", "decline") — reviewer hint
  - trace (tags from the planning phase, for explainability)
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore
    from latticed.v2.perceive.perception import Perception


# ── Slot constraints ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class SlotConstraint:
    """What a filled slot must satisfy. Constraint failure on a model
    slot triggers one retry with a tightened prompt; failure on retry
    falls back to the slot's fallback_value (which the strategy MUST
    provide for model slots — so we never serve a broken slot)."""
    max_words: int = 30
    min_words: int = 0
    must_end_with: Optional[str] = None       # e.g. "?" for question slots
    must_not_contain: tuple[str, ...] = ()    # exact (case-insensitive) phrases
    must_contain: tuple[str, ...] = ()        # any one of these is enough
    banned_patterns: tuple[str, ...] = ()     # regex patterns
    no_banned_plurals: bool = False           # we/us/our/we're etc.

    def validate(self, text: str) -> Optional[str]:
        """Return None if text passes, else a short failure reason."""
        if not text or not text.strip():
            return "empty"
        words = text.split()
        if len(words) > self.max_words:
            return f"too_long({len(words)}>{self.max_words})"
        if len(words) < self.min_words:
            return f"too_short({len(words)}<{self.min_words})"
        if self.must_end_with and not text.rstrip().endswith(self.must_end_with):
            return f"missing_end({self.must_end_with!r})"
        lo = text.lower()
        for forbidden in self.must_not_contain:
            if forbidden.lower() in lo:
                return f"contains({forbidden!r})"
        if self.must_contain:
            if not any(c.lower() in lo for c in self.must_contain):
                return "missing_required_phrase"
        for pat in self.banned_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return f"matches_banned({pat!r})"
        if self.no_banned_plurals:
            if re.search(r"\b(?:we|us|our|we're|we've|we'll|we'd|ourselves)\b",
                         text, re.IGNORECASE):
                return "banned_plural"
        return None


# ── Slot ──────────────────────────────────────────────────────────────────
class SlotKind(str, Enum):
    LITERAL = "literal"
    CHOICE  = "choice"
    KSTORE  = "kstore"
    MODEL   = "model"


@dataclass(frozen=True)
class Slot:
    """A single named slot in a ResponsePlan.

    Use the class methods (Slot.literal / Slot.choice / Slot.kstore /
    Slot.model) to construct — they enforce per-kind invariants.
    """
    name: str
    kind: SlotKind
    # LITERAL
    literal_value: Optional[str] = None
    # CHOICE
    choices: tuple[str, ...] = ()
    # KSTORE
    kstore_fn: Optional[Callable[["KStore", "Perception"], str]] = None
    # MODEL
    model_prompt: Optional[str] = None
    model_temperature: float = 0.5
    model_max_tokens: int = 60
    fallback_value: str = ""            # used if model slot fails after retry
    # All kinds
    constraint: SlotConstraint = field(default_factory=SlotConstraint)

    # -- constructors ------------------------------------------------------
    @staticmethod
    def literal(name: str, value: str,
                constraint: Optional[SlotConstraint] = None) -> "Slot":
        return Slot(
            name=name, kind=SlotKind.LITERAL, literal_value=value,
            constraint=constraint or SlotConstraint(),
        )

    @staticmethod
    def choice(name: str, options: tuple[str, ...],
               constraint: Optional[SlotConstraint] = None) -> "Slot":
        if not options:
            raise ValueError("Slot.choice requires at least one option")
        return Slot(
            name=name, kind=SlotKind.CHOICE, choices=options,
            constraint=constraint or SlotConstraint(),
        )

    @staticmethod
    def kstore(name: str, fn: Callable[["KStore", "Perception"], str],
               constraint: Optional[SlotConstraint] = None) -> "Slot":
        return Slot(
            name=name, kind=SlotKind.KSTORE, kstore_fn=fn,
            constraint=constraint or SlotConstraint(),
        )

    @staticmethod
    def model(name: str, prompt: str, *,
              fallback_value: str,
              temperature: float = 0.5,
              max_tokens: int = 60,
              constraint: Optional[SlotConstraint] = None) -> "Slot":
        if not fallback_value:
            raise ValueError("MODEL slots require a fallback_value")
        return Slot(
            name=name, kind=SlotKind.MODEL,
            model_prompt=prompt,
            model_temperature=temperature,
            model_max_tokens=max_tokens,
            fallback_value=fallback_value,
            constraint=constraint or SlotConstraint(),
        )


# ── ResponsePlan ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ResponsePlan:
    """What the strategy decided. The narrator executes this without
    needing to think — every choice was already made up here."""
    strategy_name: str
    template: str                         # Python str.format with {slot_name}
    slots: tuple[Slot, ...]
    expected_shape: str = "free"          # "two_beat" / "recall" / "decline" / ...
    trace: tuple[str, ...] = ()


# ── Strategy ABC ──────────────────────────────────────────────────────────
class Strategy(ABC):
    """A response strategy. Subclasses declare match conditions and the
    plan they emit when those conditions hold."""
    name: str = ""
    priority: int = 0          # higher wins ties in router

    @abstractmethod
    def matches(self, perception: "Perception",
                kstore: "KStore") -> bool: ...

    @abstractmethod
    def plan(self, perception: "Perception",
             kstore: "KStore") -> ResponsePlan: ...


# ── NarratorBackend protocol ──────────────────────────────────────────────
class NarratorBackend(ABC):
    """Abstract model-call interface. Real implementation wraps Ollama;
    test implementations stub responses by slot name. Keeping this
    pluggable lets every test run without a live model server."""

    @abstractmethod
    async def fill_model_slot(
        self,
        slot: Slot,
        plan_context: dict[str, Any],
    ) -> str:
        """Produce a candidate string for a MODEL slot. The narrator
        will then validate it against slot.constraint."""


class StubNarratorBackend(NarratorBackend):
    """Test/dev backend: returns canned responses by slot name.

    Construct with a {slot_name: response_string} dict. If a slot isn't
    in the dict, returns the slot's fallback_value (so partial stubs
    still work for tests that only care about specific slots)."""

    def __init__(self, canned: Optional[dict[str, str]] = None) -> None:
        self._canned = canned or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def set(self, slot_name: str, response: str) -> None:
        self._canned[slot_name] = response

    async def fill_model_slot(self, slot, plan_context) -> str:
        self.calls.append((slot.name, dict(plan_context)))
        return self._canned.get(slot.name, slot.fallback_value)
