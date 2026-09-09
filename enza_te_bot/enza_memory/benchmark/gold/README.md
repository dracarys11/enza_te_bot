# ENZA Benchmark v0.1 Gold Evaluation Set

Six offline reference answers, one per ARB case. Each answer uses exactly the
six requested fields; array entries are strings. Bracketed evidence references
are relative to enza_te_bot and attribute facts to original pixels, records,
source code or explicitly stipulated scenario inputs. They are not claims of
new live observation. Interpret an inference as inference, even where supported.

Gold answers belong to the evaluator and must not be included in model case
inputs. Existing cases and scoring code are unchanged; this dataset does not
claim scorer integration or a benchmark pass. No runtime, planner, executor or
policy authority is created. Descriptions of historical recovery or acceptable
benchmark reasoning are not permission to perform actions.

freeze_manifest.json binds each gold answer, ARB case and all direct input
artifacts to SHA-256. A changed digest means the frozen evidence version has
drifted and requires review; do not silently regenerate expected answers.
Revisions should receive a deliberate new dataset version. The manifest does
not snapshot the contents of recursively linked artifacts.

Nuances preserved: historical post-hoc risk gate versus stipulated active gate;
pause-time UNKNOWN versus later reconciled week consumption; review annotations
versus inspected pixels; event-level PASS versus run-level abandonment; nested
null versus absent event fields. No numeric confidence is invented.

Validation: 6/6 ARB cases have exactly one gold answer; required fields and types,
nonempty UNKNOWN/hard-fail lists, evidence file availability and SHA-256 bindings
were checked offline. These are dataset checks, not project tests or live runs.
