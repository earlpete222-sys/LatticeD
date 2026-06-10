"""
Sprint 0-12 regression aggregator.

Runs every test_sprint*.py module in this directory as a subprocess so
they each get a clean module-state.  Exit code 0 only if every sprint
passes 100%.

Usage:
    python tests/run_all.py
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    scripts = sorted(
        list(HERE.glob("test_sprint*.py")) + list(HERE.glob("test_phase*.py")),
        # sprint files sort numerically, phase files trail.
        key=lambda p: (0 if "sprint" in p.stem else 1,
                       int("".join(c for c in p.stem if c.isdigit()) or "0")),
    )
    if not scripts:
        print("No test_sprint*.py files found.")
        return 1

    total_run = 0
    total_pass = 0
    sprint_lines: list[str] = []
    any_failed = False

    for script in scripts:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True,
        )
        # Last line that contains "Sprint N tests passed" is the summary.
        summary_line = ""
        for line in (proc.stdout or "").splitlines()[::-1]:
            if "tests passed." in line:
                summary_line = line.strip()
                break
        if not summary_line:
            sprint_lines.append(f"[??]  {script.name} (no summary line)")
            any_failed = True
            continue

        # Parse "N/M Sprint X tests passed."
        try:
            counts = summary_line.split(" ", 1)[0]
            num, den = counts.split("/")
            n, m = int(num), int(den)
            total_run += m
            total_pass += n
            if n == m:
                sprint_lines.append(f"[OK]  {script.name:30s} {n}/{m}")
            else:
                sprint_lines.append(f"[XX]  {script.name:30s} {n}/{m}")
                any_failed = True
                # Surface the FAIL lines for fast diagnosis.
                for line in (proc.stdout or "").splitlines():
                    if line.startswith("[XX]"):
                        sprint_lines.append("       " + line)
        except Exception:
            sprint_lines.append(f"[??]  {script.name} (parse failed)")
            any_failed = True

    print("=" * 64)
    print("LatticeD - Sprint 0-12 regression")
    print("=" * 64)
    for line in sprint_lines:
        print(line)
    print("-" * 64)
    print(f"Cumulative: {total_pass}/{total_run} tests passed across {len(scripts)} sprint(s).")
    print("=" * 64)
    return 0 if not any_failed and total_pass == total_run else 1


if __name__ == "__main__":
    sys.exit(main())
