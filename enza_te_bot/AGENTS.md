# Agent map

Before changing production code, read:

1. `CURRENT_MILESTONE.md`
2. `.agent-harness/CORE.md`
3. `.agent-harness/MODES.md`
4. `.agent-harness/GATES.md`
5. `.agent-harness/profiles/enza.md`

Use the smallest evidence-backed change, preserve verified behavior, and do not run live automation without explicit authorization.

MANDATORY after any test/benchmark/live session that touches the enza environment (observation or action):
follow `enza_memory/MEMORY_PROTOCOL.md` and update observations / trajectories / failures / policies / memory_index.json before ending the session. A session with environment contact but no memory update is incomplete.

For an explicitly authorized live repair loop, also read `.agent-harness/LIVE_DEBUG.md` and pass `LIVE_DEBUG_GATE` before executing the command.
