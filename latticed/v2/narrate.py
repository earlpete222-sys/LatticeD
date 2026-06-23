"""narrate — slot-filling executor for v2 ResponsePlans.

Given a ResponsePlan + a NarratorBackend (real Ollama or test stub),
walks the slots in order, fills each according to its kind, validates
against its SlotConstraint, retries model slots once with a tightened
prompt on validation failure, and falls back to the slot's
fallback_value if retry fails.

Returns a NarratedResponse with the final text + full per-slot trace.
The trace is the auditability promise of v2: every output explains
itself.
"""
from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from latticed.v2.strategies.base import (
    NarratorBackend,
    ResponsePlan,
    Slot,
    SlotKind,
)

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore
    from latticed.v2.perceive.perception import Perception


logger = logging.getLogger("latticed.v2.narrate")


@dataclass(frozen=True)
class SlotResult:
    name: str
    value: str
    kind: SlotKind
    used_fallback: bool = False
    validation_failures: tuple[str, ...] = ()
    retried: bool = False


@dataclass(frozen=True)
class NarratedResponse:
    text: str
    strategy_name: str
    expected_shape: str
    slot_results: tuple[SlotResult, ...]
    plan_trace: tuple[str, ...] = ()

    @property
    def used_any_fallback(self) -> bool:
        return any(r.used_fallback for r in self.slot_results)


def _stable_choice(options: tuple[str, ...], seed_text: str) -> str:
    """Pick one option deterministically from ``seed_text`` so the same
    user input doesn't surface a different choice on every retry. Helps
    the reviewer layer reason about whether a regenerated reply is
    'the same' as the prior one."""
    if not options:
        return ""
    h = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


async def _fill_one_slot(
    slot: Slot,
    *,
    plan_context: dict,
    backend: NarratorBackend,
    kstore: "KStore",
    perception: "Perception",
) -> SlotResult:
    """Resolve a single slot to a string + record what happened."""
    if slot.kind == SlotKind.LITERAL:
        value = slot.literal_value or ""
        failure = slot.constraint.validate(value)
        return SlotResult(
            name=slot.name, value=value, kind=slot.kind,
            validation_failures=((failure,) if failure else ()),
        )

    if slot.kind == SlotKind.CHOICE:
        value = _stable_choice(slot.choices, perception.user_input + slot.name)
        return SlotResult(name=slot.name, value=value, kind=slot.kind)

    if slot.kind == SlotKind.KSTORE:
        if slot.kstore_fn is None:
            return SlotResult(
                name=slot.name, value=slot.literal_value or "", kind=slot.kind,
                used_fallback=True,
                validation_failures=("no_kstore_fn",),
            )
        try:
            value = slot.kstore_fn(kstore, perception)
        except Exception as e:
            logger.warning("[narrate] kstore slot %s raised %s", slot.name, e)
            return SlotResult(
                name=slot.name, value="", kind=slot.kind,
                used_fallback=True,
                validation_failures=(f"kstore_raise:{type(e).__name__}",),
            )
        return SlotResult(name=slot.name, value=value, kind=slot.kind)

    if slot.kind == SlotKind.MODEL:
        candidate = await backend.fill_model_slot(slot, plan_context)
        failure = slot.constraint.validate(candidate)
        if failure is None:
            return SlotResult(name=slot.name, value=candidate, kind=slot.kind)

        # Retry once with a tightened prompt that names the failure.
        logger.info("[narrate] slot %s failed (%s) -- retrying once",
                    slot.name, failure)
        retried_slot = Slot.model(
            name=slot.name,
            prompt=(slot.model_prompt or "")
                   + f"\n\nYour previous attempt failed: {failure}. "
                     f"Try again, strictly following the rules above. "
                     f"Be shorter if needed.",
            fallback_value=slot.fallback_value,
            temperature=max(0.0, slot.model_temperature - 0.15),
            max_tokens=slot.model_max_tokens,
            constraint=slot.constraint,
        )
        candidate2 = await backend.fill_model_slot(retried_slot, plan_context)
        failure2 = slot.constraint.validate(candidate2)
        if failure2 is None:
            return SlotResult(
                name=slot.name, value=candidate2, kind=slot.kind,
                validation_failures=(failure,),
                retried=True,
            )
        # Retry failed too -- ship the fallback.
        logger.warning(
            "[narrate] slot %s failed twice (%s, %s) -- using fallback",
            slot.name, failure, failure2,
        )
        return SlotResult(
            name=slot.name, value=slot.fallback_value, kind=slot.kind,
            used_fallback=True, retried=True,
            validation_failures=(failure, failure2),
        )

    # Unknown kind -- defensive
    return SlotResult(
        name=slot.name, value=slot.literal_value or slot.fallback_value or "",
        kind=slot.kind, used_fallback=True,
        validation_failures=(f"unknown_kind:{slot.kind}",),
    )


async def narrate(
    plan: ResponsePlan,
    *,
    backend: NarratorBackend,
    kstore: "KStore",
    perception: "Perception",
) -> NarratedResponse:
    """Execute a ResponsePlan into a final string reply.

    Slot results accumulate into ``plan_context`` as each slot is filled,
    so later model slots can reference earlier outputs (the reflection
    slot's result is available when filling the question slot).
    """
    plan_context: dict = {
        "user_input": perception.user_input,
        "intent": perception.intent.value,
    }
    slot_results: list[SlotResult] = []
    filled: dict[str, str] = {}

    for slot in plan.slots:
        result = await _fill_one_slot(
            slot,
            plan_context=plan_context,
            backend=backend,
            kstore=kstore,
            perception=perception,
        )
        slot_results.append(result)
        filled[slot.name] = result.value
        plan_context[slot.name] = result.value

    try:
        text = plan.template.format(**filled)
    except KeyError as e:
        logger.error("[narrate] template missing slot %s; plan=%s",
                     e, plan.strategy_name)
        text = " ".join(v for v in filled.values() if v).strip()

    # Clean up double spaces from collapsed fallbacks
    text = " ".join(text.split())

    return NarratedResponse(
        text=text,
        strategy_name=plan.strategy_name,
        expected_shape=plan.expected_shape,
        slot_results=tuple(slot_results),
        plan_trace=plan.trace,
    )
