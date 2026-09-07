# enza profile

Project: fixed-UI visual game automation.
Workflow: Demonstration-First Automation (SOP → demonstration → model → review → bounded run → annotation).

Primary milestone: first verified `TE_SUCCESS`.

Implementation preference: fixed deterministic behavior; existing taught actions; template/OCR; bounded local CV; generic perception only when simpler options are proven insufficient.

Before first `TE_SUCCESS`, defer generic GUI parsing, runtime LLM, broad visual-agent frameworks, workflow DSL, reusable framework extraction, and non-blocking architecture refactors.

Preserve dynamic game-window and Retina mapping, normalized clicks, PyAutoGUI FAILSAFE, UNKNOWN fail-closed behavior, action-sent versus committed semantics, effect verification, atomic config writes, and no live execution by the coding agent unless explicitly authorized.

LIVE_DEBUG examples:

- `.venv/bin/python main.py --observe-home` is `LEVEL_0_OBSERVE_ONLY`: click scope `NONE`; terminal condition is a committed HOME observation or structured unreadable result.
- `.venv/bin/python main.py --post-audition-cleanup --live` is `LEVEL_1_BOUNDED_SAFE_UI` only when explicitly approved: click scope is the existing bounded cleanup capabilities/regions; terminal condition is the configured cleanup boundary; protected states and existing timeout/max-click/no-effect bounds retain precedence.
