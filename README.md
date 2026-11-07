# French Interview Research Loop — ready-to-run starter

**Dataset:** 192 French `.trs` transcripts. **Tasks:** interviewee's age bracket, gender, interview year. The supplied claim that years are only 1970 / 2005 is **not yet verified**: `S035.trs` contains interviewee language referring to being in 2010.

## Run the zero-cost baseline

Python 3.10+; no external dependencies required.

```bash
python -m unittest discover -s tests -v
python -m src.pipeline --archive data/impactLab.zip
```

**v2 (current, frozen):** `python -m src.run_v2` → `outputs/predictions.csv`, `outputs/evidence.json`, `outputs/summary_v2.json`, `segments` table in `outputs/interviews.sqlite`. Freeze manifest: `outputs/FREEZE_rules_v2.json`. See REPORT.md.

**LLM stage (plan-only by default):** `python -m src.llm_infer --ids S035,S002 --out outputs/llm_pilot` prints chunk counts and cost; real calls need `--execute --approved-budget-usd N --ids ...` and `pip install anthropic`.

v1 outputs: `outputs/interviews.sqlite` (turn-level database), `outputs/baseline.csv` (192 interview rows with `unknown`/blank as appropriate), `outputs/baseline_evidence.json`, `outputs/summary.json`. No Claude API calls, no ground truth used. The importer uses SQLite only for portability; see `sql/postgres_schema.sql` for PostgreSQL setup and queries.

## Run a research loop in Claude Code

Open a terminal in this folder and run `claude update`, then launch `claude`. The workshop instructions recommend Claude Code v2.1.139+ for `/goal`.

```
/goal All 192 transcripts parse, all tests pass, and a valid prediction row plus evidence record exists for each interview, with year contradictions explicitly flagged and documented in REPORT.md. Continue the goal in PROMPT.md. Take the top task in TASKS.md, test first, implement, verify and journal results. Do not read ground truth and request approval before any paid LLM calls.
```

The installed CLI may differ from the workshop documentation; check `/help` if `/goal` is unavailable. `/loop` is useful for periodic checks, **not needed** for processing every transcript.

## Data integrity and evaluation

* No answer key is packaged or read.
* Parser labels overlapping speaker turns as `overlap` so dialogue isn't misattributed.
* Regex matches are candidate evidence, not guaranteed truth; gender grammar is not identical to gender identity.
* Use null/unknown when not sufficiently grounded.
* Before final evaluation freeze the full prediction file, model settings, prompt and source list.
* Check permission/privacy safeguards before sending transcripts to external AI providers.

## What this starter actually does

A working **parser, baseline and tests**, not a completed Claude inference run. The baseline deliberately leaves interview year blank rather than fabricating labels; this is a benchmark for coverage and additional research, not a full solution.

## Evaluate after predictions are frozen

Once the organizer provides a ground-truth CSV **outside** the research workspace with columns `interview_id,age_bracket,gender,interview_year`, run:

```bash
python -m src.evaluate --predictions outputs/baseline.csv --ground-truth /secure/path/ground_truth.csv --output evaluation.json
```

The evaluator checks matching IDs and reports **coverage and accuracy on answered records separately** plus confusion counts. It is never called by the extraction pipeline. Age categories must be normalized to the same bin convention in both files before comparing.
