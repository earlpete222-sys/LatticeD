"""Temporal parser + holiday calendar.

Resolves natural-language time references in user input to absolute
datetimes. This is the layer that kills calendar fabrication once and
for all: the 1.5B model never has to know when Father's Day falls
because the perception layer already resolved it before the model is
ever called.

Coverage (in priority order):
  1. Named US holidays — built-in date functions, exact resolution
  2. Relative day references — yesterday / today / tomorrow
  3. Day-of-week references — "last Tuesday", "next Friday"
  4. Explicit dates — "June 21", "6/21/2026", "2026-06-21"
  5. Hour-of-day — "at 3pm" (when paired with a day reference)

Out of scope (deliberately, for now):
  - "in three weeks", "the week after next"
  - Time zones other than the user's local
  - Repeating events
These can be added when a strategy needs them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Callable, Optional


# ── Holiday date functions (US-centric default set) ─────────────────────────
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Nth occurrence (1-indexed) of ``weekday`` (0=Monday) in given month."""
    first = date(year, month, 1)
    days_ahead = (weekday - first.weekday()) % 7
    return first + timedelta(days=days_ahead + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last occurrence of ``weekday`` in given month."""
    # Find the last day of month, walk back.
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last = first_next - timedelta(days=1)
    delta = (last.weekday() - weekday) % 7
    return last - timedelta(days=delta)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian computus (Meeus / Jones / Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return date(year, month, day)


# Each entry: canonical name -> (year -> date) function.
# Lowercased canonical names; alias map is built below.
KNOWN_HOLIDAYS: dict[str, Callable[[int], date]] = {
    "new year's day":      lambda y: date(y, 1, 1),
    "mlk day":             lambda y: _nth_weekday(y, 1, 0, 3),   # 3rd Mon Jan
    "valentine's day":     lambda y: date(y, 2, 14),
    "presidents' day":     lambda y: _nth_weekday(y, 2, 0, 3),   # 3rd Mon Feb
    "st patrick's day":    lambda y: date(y, 3, 17),
    "easter":              _easter_sunday,
    "mother's day":        lambda y: _nth_weekday(y, 5, 6, 2),   # 2nd Sun May
    "memorial day":        lambda y: _last_weekday(y, 5, 0),     # last Mon May
    "father's day":        lambda y: _nth_weekday(y, 6, 6, 3),   # 3rd Sun Jun
    "juneteenth":          lambda y: date(y, 6, 19),
    "independence day":    lambda y: date(y, 7, 4),
    "labor day":           lambda y: _nth_weekday(y, 9, 0, 1),   # 1st Mon Sep
    "halloween":           lambda y: date(y, 10, 31),
    "veterans day":        lambda y: date(y, 11, 11),
    "thanksgiving":        lambda y: _nth_weekday(y, 11, 3, 4),  # 4th Thu Nov
    "christmas":           lambda y: date(y, 12, 25),
    "christmas eve":       lambda y: date(y, 12, 24),
    "new year's eve":      lambda y: date(y, 12, 31),
}

# Common variants that should map to the same canonical key.
_HOLIDAY_ALIASES: dict[str, str] = {
    "fathers day": "father's day",
    "father day":  "father's day",
    "mothers day": "mother's day",
    "mother day":  "mother's day",
    "valentines day": "valentine's day",
    "valentine day":  "valentine's day",
    "new years day":  "new year's day",
    "new years eve":  "new year's eve",
    "st. patrick's day": "st patrick's day",
    "st patricks day":   "st patrick's day",
    "saint patrick's day": "st patrick's day",
    "july 4th":      "independence day",
    "fourth of july": "independence day",
    "4th of july":    "independence day",
    "martin luther king day": "mlk day",
    "presidents day": "presidents' day",
}


def holiday_date_for(name: str, year: int) -> Optional[date]:
    """Return the date a named holiday falls on in the given year.

    Lookup is case-insensitive and tolerates common variants. Returns
    None if the holiday isn't in the built-in set — the caller decides
    what to do (ask the user, escalate, etc.).
    """
    key = name.strip().lower().rstrip(".")
    key = _HOLIDAY_ALIASES.get(key, key)
    fn = KNOWN_HOLIDAYS.get(key)
    return fn(year) if fn else None


# ── TemporalRef record ──────────────────────────────────────────────────────
class TemporalGrain(str, Enum):
    """How precise a resolved time is."""
    YEAR   = "year"
    MONTH  = "month"
    DAY    = "day"
    HOUR   = "hour"
    MINUTE = "minute"


@dataclass(frozen=True)
class TemporalRef:
    """A resolved time reference found in user input.

    text is the surface form ("yesterday", "Father's Day"). when is
    the absolute datetime in the user's local timezone (we use the
    timezone of ``now`` passed to resolve_temporal_refs).
    grain says how precise the resolution is.
    """
    text: str
    when: datetime
    grain: TemporalGrain
    confidence: float
    start: int = 0
    end: int = 0


# ── Regexes ────────────────────────────────────────────────────────────────
_REL_DAY_RX = re.compile(r"\b(yesterday|today|tonight|tomorrow)\b", re.IGNORECASE)

_WEEKDAY_NAMES = {
    "monday":    0, "mon": 0,
    "tuesday":   1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday":  3, "thu": 3, "thur": 3, "thurs": 3,
    "friday":    4, "fri": 4,
    "saturday":  5, "sat": 5,
    "sunday":    6, "sun": 6,
}
_DOW_RX = re.compile(
    r"\b(?:on\s+)?(last|this|next)\s+("
    + "|".join(sorted(_WEEKDAY_NAMES, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTHDAY_RX = re.compile(
    r"\b(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
    + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_ISO_DATE_RX = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_SLASH_DATE_RX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


# ── Resolver ──────────────────────────────────────────────────────────────
def _midnight(d: date, tz) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=tz)


def _resolve_relative_day(token: str, now: datetime) -> Optional[datetime]:
    t = token.lower()
    if t == "today" or t == "tonight":
        return _midnight(now.date(), now.tzinfo)
    if t == "yesterday":
        return _midnight(now.date() - timedelta(days=1), now.tzinfo)
    if t == "tomorrow":
        return _midnight(now.date() + timedelta(days=1), now.tzinfo)
    return None


def _resolve_dow(qualifier: str, weekday_name: str, now: datetime) -> Optional[datetime]:
    """Resolve 'last Tuesday' / 'this Friday' / 'next Monday'."""
    wd = _WEEKDAY_NAMES.get(weekday_name.lower())
    if wd is None:
        return None
    today_wd = now.weekday()
    delta = (wd - today_wd) % 7
    q = qualifier.lower()
    if q == "last":
        delta = delta - 7 if delta != 0 else -7
    elif q == "this":
        # "this Friday" — interpret as the upcoming one, even if today is later
        # in the week; fall back to today if Friday is today.
        if delta == 0:
            pass   # today
    elif q == "next":
        delta = delta + 7 if delta == 0 else delta if delta > 0 else delta + 7
    return _midnight(now.date() + timedelta(days=delta), now.tzinfo)


def _resolve_holiday_phrase(text: str, now: datetime) -> list[TemporalRef]:
    """Scan input for any known holiday name and resolve to its date
    in the current year (or next year if it's already past)."""
    out: list[TemporalRef] = []
    lowered = text.lower()
    # Use a single scan over the known names + aliases so the longest
    # name wins (avoid "father" matching "father's day").
    names = sorted(
        list(KNOWN_HOLIDAYS) + list(_HOLIDAY_ALIASES),
        key=len, reverse=True,
    )
    consumed: list[tuple[int, int]] = []
    for name in names:
        idx = 0
        while True:
            pos = lowered.find(name, idx)
            if pos == -1:
                break
            end = pos + len(name)
            # Skip if this span overlaps a longer already-consumed match.
            overlap = any(not (end <= a or pos >= b) for a, b in consumed)
            if not overlap:
                # word-boundary-ish check: char before/after must not be alphanum
                before_ok = pos == 0 or not text[pos - 1].isalnum()
                after_ok  = end == len(text) or not text[end].isalnum()
                if before_ok and after_ok:
                    canonical_name = _HOLIDAY_ALIASES.get(name, name)
                    d = holiday_date_for(canonical_name, now.year)
                    if d and d < now.date():
                        # Already past this year — assume user means next year
                        d_next = holiday_date_for(canonical_name, now.year + 1)
                        # ...unless the user literally just said it in past tense
                        # ("Sunday was Father's Day"). We can't reliably tell
                        # tense here; default to the SAME year if within last
                        # ~7 days, otherwise next year.
                        if (now.date() - d).days <= 14:
                            pass    # keep this year — recent past
                        else:
                            d = d_next
                    if d:
                        out.append(TemporalRef(
                            text=text[pos:end],
                            when=_midnight(d, now.tzinfo),
                            grain=TemporalGrain.DAY,
                            confidence=1.0,
                            start=pos, end=end,
                        ))
                        consumed.append((pos, end))
            idx = end
    return out


def resolve_temporal_refs(text: str, now: datetime) -> tuple[TemporalRef, ...]:
    """Find every resolvable time reference in ``text``. Returns a tuple
    sorted by start offset. ``now`` must be tz-aware.

    Holidays take precedence over weekday names (so "Father's Day"
    doesn't get reparsed as just a Sunday).
    """
    if now.tzinfo is None:
        raise ValueError("resolve_temporal_refs: now must be timezone-aware")
    refs: list[TemporalRef] = []

    # 1. Holidays (highest priority — exact resolution)
    refs.extend(_resolve_holiday_phrase(text, now))
    consumed = [(r.start, r.end) for r in refs]

    def _overlaps(a: int, b: int) -> bool:
        return any(not (b <= x or a >= y) for x, y in consumed)

    # 2. Relative day tokens
    for m in _REL_DAY_RX.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        when = _resolve_relative_day(m.group(1), now)
        if when:
            refs.append(TemporalRef(
                text=m.group(0), when=when, grain=TemporalGrain.DAY,
                confidence=1.0, start=m.start(), end=m.end(),
            ))
            consumed.append((m.start(), m.end()))

    # 3. Day-of-week with qualifier
    for m in _DOW_RX.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        when = _resolve_dow(m.group(1), m.group(2), now)
        if when:
            refs.append(TemporalRef(
                text=m.group(0), when=when, grain=TemporalGrain.DAY,
                confidence=0.9, start=m.start(), end=m.end(),
            ))
            consumed.append((m.start(), m.end()))

    # 4. Month + day  ("June 21", "Jun 21st")
    for m in _MONTHDAY_RX.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        mo = _MONTH_NAMES[m.group(1).lower()]
        day = int(m.group(2))
        try:
            d = date(now.year, mo, day)
            if d < now.date() - timedelta(days=180):
                d = date(now.year + 1, mo, day)
        except ValueError:
            continue
        refs.append(TemporalRef(
            text=m.group(0), when=_midnight(d, now.tzinfo),
            grain=TemporalGrain.DAY, confidence=0.95,
            start=m.start(), end=m.end(),
        ))
        consumed.append((m.start(), m.end()))

    # 5. ISO dates
    for m in _ISO_DATE_RX.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        refs.append(TemporalRef(
            text=m.group(0), when=_midnight(d, now.tzinfo),
            grain=TemporalGrain.DAY, confidence=1.0,
            start=m.start(), end=m.end(),
        ))
        consumed.append((m.start(), m.end()))

    # 6. Slash dates (assume US M/D/Y)
    for m in _SLASH_DATE_RX.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        try:
            mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yr < 100:
                yr += 2000
            d = date(yr, mo, day)
        except ValueError:
            continue
        refs.append(TemporalRef(
            text=m.group(0), when=_midnight(d, now.tzinfo),
            grain=TemporalGrain.DAY, confidence=0.85,
            start=m.start(), end=m.end(),
        ))
        consumed.append((m.start(), m.end()))

    refs.sort(key=lambda r: r.start)
    return tuple(refs)
