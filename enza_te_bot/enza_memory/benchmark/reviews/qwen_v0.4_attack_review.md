# Critical Findings

ID: F-001
Severity: P0
Category: Artifact Completeness / Evidence Dependency
Evidence: `enza_memory/benchmark/RELEASE_v0.3.md` (Known limitations) states: "`case_201` references `enza_memory/observations/OBS_012.json`. That evidence record exists in the release workspace but is not part of this benchmark package or its committed baseline, so a clean-checkout evidence-availability check will report that external dependency missing."
Risk: The benchmark is not self-contained. A clean checkout of the release commit will fail preflight validation for `case_201` because a required input artifact (`OBS_012.json`) is absent from the repository. This makes the benchmark impossible to reproduce or validate in a standard CI/CD or fresh-clone environment without external, undocumented file injection.
Mitigation: Commit `enza_memory/observations/OBS_012.json` to the repository as part of the benchmark package, or explicitly exclude `case_201` from the v0.3 baseline until the dependency is resolved.

ID: F-002
Severity: P0
Category: Reproducibility / Model Comparison Fairness
Evidence: `enza_memory/benchmark/RELEASE_v0.3.md` (Reproducibility) states: "The archived leaderboard reports all three participants at `170 / 200` using the unchanged evaluator."
Risk: All three participants achieving an identical score of 170/200 on a 2-case benchmark (max 200 points) is statistically anomalous for distinct AI agents. This suggests either: (1) the "participants" are not distinct models but identical runs or placeholders; (2) the scoring is saturated or broken (e.g., all pass/fail rules are identical for all inputs); or (3) the baseline is fabricated/placeholder data. This invalidates any claim of model comparison or reliability differentiation.
Mitigation: Provide raw, distinct model outputs for the three participants. If the score is identical, provide evidence that the models produced semantically distinct but equally correct answers, or remove the "model comparison" claim from the release scope.

ID: F-003
Severity: P1
Category: Evaluator Integrity
Evidence: `enza_memory/benchmark/RELEASE_v0.3.md` (Evaluator status) states: "The archived v0.3 baseline reports the current scoring behavior explicitly, including the rule-prefix limitation that assigns five unknown-handling points for these case contracts."
Risk: The evaluator is not fully deterministic or neutral. It explicitly awards points for "unknown-handling" (5 points). This creates a bias where models that correctly identify ambiguity and return "UNKNOWN" are rewarded, while models that attempt an answer (even if wrong) are penalized. This conflates "epistemic humility" with "correctness" and may not align with the intended reliability dimension (e.g., "Observation failure must not trigger business recovery"). If the gold answer is a specific action, but the evaluator rewards "UNKNOWN", the benchmark measures caution rather than reliability.
Mitigation: Clarify the scoring rubric. If "UNKNOWN" is a valid correct answer for specific cases, the gold answer must reflect that. If "UNKNOWN" is a fallback, the 5-point bonus should be removed or justified as a separate "calibration" metric, not part of the core reliability score.

ID: F-004
Severity: P1
Category: Release Validity / Artifact Completeness
Evidence: `enza_memory/benchmark/RELEASE_v0.3.md` (Known limitations) states: "The v0.2 archive contains six promoted ARB packages and six gold answers, while its normalized baseline run contains five cases and omits `case_103`. This historical structure is preserved rather than normalized during the v0.3 freeze."
Risk: The release package contains inconsistent data between the "promoted" cases (6) and the "baseline run" (5). This creates ambiguity for any consumer trying to validate the v0.2 compatibility archive. It is unclear whether `case_103` is invalid, missing, or intentionally excluded. This inconsistency undermines the "compatibility archive" claim and makes historical comparison unreliable.
Mitigation: Either include `case_103` in the baseline run or explicitly document why it is excluded (e.g., "deprecated", "failed validation"). The release document should not "preserve" an inconsistency without explanation.

ID: F-005
Severity: P2
Category: Reproducibility
Evidence: `enza_memory/benchmark/RELEASE_v0.3.md` (Reproducibility) states: "Re-score copies of the archived submissions with the existing evaluator if independent score reproduction is required. Do not overwrite the archive."
Risk: The release does not provide a script or command to re-score the archived submissions. It relies on the user to "re-score copies" using the "existing evaluator", which is described as "outside this freeze commit". This makes independent verification of the scores (170/200) impossible without access to the evaluator source code, which is not included in the release package.
Mitigation: Include the evaluator source code or a pinned version of the evaluator in the release package, or provide a script that automates the re-scoring process.

# Questions Before Release

1. Why do all three participants have an identical score of 170/200? Are these distinct models, and if so, what is the variance in their raw outputs?
2. Is `enza_memory/observations/OBS_012.json` intended to be a public artifact? If so, why is it not committed to the repository?
3. What is the specific rule for the "five unknown-handling points"? Is "UNKNOWN" a correct answer for `case_201` and `case_202`, or is it a penalty mitigation?
4. Why is `case_103` omitted from the v0.2 baseline run? Is it a known bad case, or is it a packaging error?
5. Where is the evaluator source code? The release states it is "outside this freeze commit", but independent verification requires access to it.

# Final Verdict

NOT READY
