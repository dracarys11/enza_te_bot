# benchmark_results/ — offline evaluation runs

Each `benchmark_runner.py generate --executor {vlm,agent,human}` invocation
creates one run directory here:

    run_<UTC timestamp>_<executor>/
        run_manifest.json      executor, verdict, per-case PENDING records
        eval_<case_id>.md      evaluation template per case

Workflow:

1. `python3 benchmark_runner.py validate` — load + validate every
   `benchmark_cases/case_*.json` (schema, evidence existence, sha256);
   writes nothing.
2. `python3 benchmark_runner.py generate --executor <vlm|agent|human>` —
   fail-closed: a run is written only when every case validates.
3. The executor fills `actual_behavior` and `pass/fail` in each template.
   The `expected_behavior` / grading sections are evaluator reference and
   must not be disclosed to a system under test before its answer is
   recorded.

The runner performs no observation and no action; `execution_performed` in
every manifest is structurally `false`.
