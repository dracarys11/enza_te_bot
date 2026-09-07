# Demonstration-First Automation Workflow

Human SOP → passive demonstration → deterministic model → human review → bounded automation → exception annotation → reviewed evidence.

Phases: DISCOVER/SOP, DEMONSTRATE/RECORD, MODEL/COMPILE, VERIFY/REVIEW, AUTOMATE/RUN, ANNOTATE/EXCEPTION REVIEW.

Use this workflow for browser, RPA, desktop, game, approval, and repetitive operational automation where a human already knows the procedure. It is not a default for open-ended research or greenfield design.

Facts, inferences, provisional claims, and unknowns must remain distinct. Annotation never activates production behavior directly; it follows ANNOTATION → COMPILE → VERIFY → PROMOTE.

Verified automation may enter the bounded `LIVE_DEBUG` repair loop only after `LIVE_DEBUG_GATE` passes. Live debugging retries the same approved command; it never authorizes the next workflow transaction.
