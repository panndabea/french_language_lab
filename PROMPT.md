# Research loop: French interview metadata challenge

## Goal
Create a reproducible, honest, **ground-truth-blind** prediction pipeline for all 192 `impactLab/S###.trs` interviews. Predict interviewee age bracket (0-9, 10-19, ..., 80-89, 90+), gender (female/male/unknown) and interview year (1970/2005/unknown). Preserve supporting exact French quotes, speaker IDs, timestamps, and counterevidence. Allow unknown values. Track conflicts against the stated year taxonomy. Optionally explore occupation, living location, movement and topics as unverified exploratory descriptions.

## Grounding issue discovered
S035 contains interviewee text `donc euh on est en deux mille dix` (2010). Do **not** hardcode 2005 in such cases; verify whether the years describe recording dates, corpus cohorts or something else. Keep a separate `out_of_domain_year_flag` and report blockers.

## Research protocol
1. Inspect actual ZIP, speaker tags, nested XML tags, mixed-speaker turns; validate 192 distinct interviews.
2. Build/test deterministic parser and SQLite/Postgres-compatible baseline. Preserve speaker turns and evidence.
3. Propose a fixed Claude extraction JSON schema, prompts and chunking approach; don't silently truncate long interviews. Analyze full interviewee context and interviewer questions.
4. For each transcript run evidence collection -> competing hypotheses -> contradiction search -> independent evidence check -> decision. Never fabricate quotes. Keep evidence tied to the interviewee and timestamps.
5. Store model/version/prompt hash/temperature/chunks/run ID for reproducibility. Freeze final predictions BEFORE looking at ground truth.
6. Create `predictions.csv` with one row for each ID and `evidence.json`; track nulls; run validation tests.
7. Ground truth is evaluated only in a separate explicitly authorized evaluation step. Report per-field accuracy on answered items and coverage; macro F1 for gender/year, age bracket accuracy and near-miss (adjacent bins), and confusion matrices.

## Research behavior
Maintain `TASKS.md` prioritized, `JOURNAL.md` as a dated append-only record, and this `PROMPT.md` as resumption context. For each coding step, write a failing test, implement and verify. Use subagents for bounded tasks where appropriate. Commit completed work if repository is initialized. Ask for approval before paid model calls and external uploads.

## Completion criteria
All 192 parsed; complete one-row-per-interview predictions with nulls allowed; valid JSON evidence; tests pass; report explicitly discusses 2010 contradiction, uncertainty, coverage and data protection; no ground truth accessed.

## Resumption state (2026-11-07)
Deterministic rules_v2.4 is done and frozen (`outputs/FREEZE_rules_v2.json`); 69 tests pass. Birth+age triangulation places cohorts near 1969 and ~2010. The LLM stage is implemented but NOT run. Waiting on: (1) user approval of pilot budget (~$1.66, ids S035,S002,S163,S001,S010) and data-protection permission; (2) organizer clarification of the 1970/2005 semantics. Next: run the pilot via `python -m src.llm_infer --execute ...`, check grounding errors, compare with rules_v2, then request approval for the full run.
Update: pilot DONE (0 grounding errors, ≈$2.72; see JOURNAL). Next: tighten decide prompt (S002 over-interpretation), add rule cues, then ask approval for full run (≈$74 Opus / ≈$37 batch).
Final state (2026-11-07): run hard-stopped at 101/192; predictions frozen (predictions_frozen.csv); evaluated; FINAL_RESEARCH_REPORT.md written. Remaining items are optional follow-ups in TASKS.md.
