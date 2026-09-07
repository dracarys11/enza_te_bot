# Modes

- **FIX**: diagnose one failure, make the minimum correction, add a regression, validate; no unrelated refactor.
- **FEATURE**: requires acceptance criteria and bounded implementation.
- **RESEARCH**: investigation only; no production source edits; deliver a research note and backlog items.
- **AUDIT**: inspect and report only.
- **REFACTOR**: explicit request and measurable benefit required; preserve behavior.
- **SPIKE**: isolated experiment; never becomes production automatically.
- **LIVE_DEBUG**: bounded execution of one explicitly approved live command under `.agent-harness/LIVE_DEBUG.md`; diagnose from evidence, apply only minimal in-scope repairs, validate offline, and retry within the declared attempt/risk bounds.

`LIVE_DEBUG` authorization is command-specific. It does not imply approval for subsequent workflow steps, broader click authority, new policy, or irreversible effects.
