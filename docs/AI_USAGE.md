# AI usage statement

## What AI did

The whole implementation was produced by an AI coding agent (Claude, Claude Code session) from the task documents.
That includes the schema, generator, rule engine, workflow simulator, validator, evaluator, tests and docs.
This is stated plainly because the submission rules ask for an honest account: the human contribution is the
task selection, review and decision to submit, not hand-written code.

## Where AI helped most

* Turning the 10-step brief into a design: schema-first single source of truth (`whmon/schema.py` drives the data
  dictionary, SQL DDL, CSV headers and validator so they cannot drift apart).
* Writing the stochastic generator and rule engine, and the unit tests for the boundary rules.
* Debugging the problems listed below.

## What was reviewed, changed and validated (by running it, not by assumption)

Problems found while running the pipeline and fixed:

| Problem found | How found | Fix |
|---|---|---|
| Lot stays overlapped in 83 lots (transfers planned past the data cutoff) | validator | transfers only created before cutoff−1h; receipts capped before cutoff |
| 23% of lots quarantined, unrealistic | evaluator KPIs | longer product excursion tolerances, lower fault rates, shorter skewed excursion durations, 2-reading hysteresis so one outage is one alarm |
| 70 drift-induced false alarms | evaluator alarm categories | impact graded `UNVERIFIED` when the breaching sensor is drift-flagged and its twin disagrees; 28 remain and are reported as false alarms |
| Validator reported 1,190 false failures | mutation/regression run | stale loop variable in impact-level check; fixed and covered by test |
| Validator crashed on an orphan foreign key | mutation test | semantic stage is skipped and recorded as a failed check when joins are broken |
| Evaluator crashed on date-only `window_start` | full run | consistent ISO timestamps; evaluator restricted to explicit event types |
| Messy door-overlap logic | validator (overlapping door events) | rewritten; 0 overlaps |

Validation evidence: 51 automated tests (incl. mutation tests that corrupt data and expect the validator to fail), the
validator's 173 passing checks over 18.5 M assertions at full scale, SQLite `PRAGMA foreign_key_check` = 0 violations,
and a regeneration-twice checksum comparison ([reproducibility_report.json](reproducibility_report.json)).

## Things I did not verify / honest caveats

   ## What I did myself
   - Downloaded and ran the project on Windows, installed Python and pytest.
   - Ran the starter generation, validation and evaluation, and all 51 tests.
   - Read the README, data dictionary, monitoring rules and assumptions.
   - Found and reported the Windows manifest-path test failure, which was then fixed.

* The numbers in the data are synthetic. Domain values (product temperature bands, door limits, rates) are plausible
  engineering choices, not drawn from a real facility or a specific regulation.
* Edge-case detectors reach precision = recall = 1.0 because they are exact rule checks on structured data and the
  defects are injected by the same generator. That demonstrates the detectors and labels agree, **not** that the
  approach would score 1.0 on messy real data.
* A human reviewer should still read the rules in `docs/` and decide whether the thresholds fit their operation.
