#!/usr/bin/env python3
"""Read-only structural check for the repository agent harness."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["CORE.md", "MODES.md", "GATES.md", "DELIVERY.md", "BACKLOG.md", "LIVE_DEBUG.md"]
PHASES = ["discover.md", "demonstrate.md", "model.md", "verify.md", "automate.md", "annotate.md"]
TEMPLATES = ["milestone.md", "task.md", "bugfix.md", "research.md", "delivery.md", "sop.md", "demonstration.md", "process_model.md", "verification.md", "exception_report.md", "annotation.md", "live_debug.md"]

def main() -> int:
    harness = ROOT / ".agent-harness"
    missing = [str(harness / name) for name in REQUIRED if not (harness / name).is_file()]
    missing += [str(harness / "templates" / name) for name in TEMPLATES if not (harness / "templates" / name).is_file()]
    missing += [str(harness / "phases" / name) for name in PHASES if not (harness / "phases" / name).is_file()]
    if not (harness / "WORKFLOW.md").is_file(): missing.append(str(harness / "WORKFLOW.md"))
    for name in ("AGENTS.md", "CURRENT_MILESTONE.md"):
        if not (ROOT / name).is_file(): missing.append(str(ROOT / name))
    profile = harness / "profiles" / "enza.md"
    if not profile.is_file(): missing.append(str(profile))
    milestone = ROOT / "CURRENT_MILESTONE.md"
    text = milestone.read_text(encoding="utf-8") if milestone.is_file() else ""
    required_headings = ("## Goal", "## Current checkpoint", "## Current blocker", "## Deferred")
    malformed = [heading for heading in required_headings if heading not in text]
    if missing or not text.strip() or malformed:
        if missing: print("missing=" + ", ".join(missing))
        if malformed: print("malformed_headings=" + ", ".join(malformed))
        return 1
    deferred = sum(1 for line in (harness / "BACKLOG.md").read_text(encoding="utf-8").splitlines() if line.startswith("- ["))
    goal = re.search(r"## Goal\n\n(.+)", text)
    checkpoint = re.search(r"## Current checkpoint\n\n(.+)", text)
    print("harness_check: OK")
    print(f"goal={goal.group(1) if goal else ''}")
    print(f"checkpoint={checkpoint.group(1) if checkpoint else ''}")
    print(f"deferred_count={deferred}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
