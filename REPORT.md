# Report — no ground truth used

> **Status 2026-11-07 16:00: HARD STOP by user.** The full LLM run was stopped after 101 of 192 interviews. Final frozen predictions: `predictions_frozen.csv` (99 LLM-decided, 93 rule fallback; 3 failed, 90 unprocessed). Spend measured at $42.18 (≈ $43.15 upper bound). See JOURNAL.md and FINAL_RESEARCH_REPORT.md. **Evaluated after freeze:** gender 99.5%, wave 100%, age 88.2% exact / 100% adjacent (when answered); details in FINAL_RESEARCH_REPORT.md §6.

# Deterministic v2 section

Date: 2026-11-07 · Prediction set: `rules_v2.4` · LLM calls: 0 · Ground truth accessed: **no**
Freeze manifest: `outputs/FREEZE_rules_v2.json` (SHA-256 of predictions, evidence, code, prompts, archive `947126bd…`).

## Dataset and parsing

- 192 distinct `impactLab/S###.trs` files (macOS AppleDouble entries ignored); every file parsed.
- Speaker table always `spk1=interviewer`, `spk2=interviewee`, optional `other1..other4` (95 interviews have ≥1 other person).
- 44,375 multi-speaker turns, each with exactly two speakers separated by `<Who nb="1"/>`/`<Who nb="2"/>`. The v1 parser discarded these as `overlap`; v2 splits them by Who marker, so each piece goes to its own speaker, flagged `overlap=True`. This is not assigning one person's speech to another: attribution follows the transcriber's markup, and malformed turns (0 found) would stay unattributed. **46,613 interviewee segments recovered.** 434,376 segments total, each with a Sync timestamp.

## Predictions (`outputs/predictions.csv`, one row per interview, nulls allowed)

| Field | Answered | Coverage | Distribution |
|---|---:|---:|---|
| age_bracket | 21 | 11% | direct statements, incl. one 90+ (S111) |
| gender | 172 | 90% | female 91, male 81, unknown 20 |
| interview_year (strict) | 98 | 51% | 1970: 48, 2005: 50 |
| cohort_hypothesis | 108 | 56% | 1970: 50, 2005: 58 |
| out_of_domain_year_flag | 10 flagged | — | S030, S035, S051, S066, S083, S091, S092, S100, S163, S192 |

22 interviews are `review_needed` (conflicts, implausible ages, or out-of-domain years). Accuracy is **not known**: no ground truth has been consulted. Coverage is not accuracy.

**Method.** Unknown is the default. Evidence lists in `outputs/evidence.json` quote the source segment verbatim with speaker ID, role, overlap flag and timestamp. A validator checks that every quote exists in the parsed source with the same speaker and timestamp: 0 errors.
- *Age*: two-digit birth years ("je suis né en quarante et un") are century-ambiguous. S111 was born in 1878, so candidates are resolved by stated age or cohort feasibility. First-person current-age statements with French number words. Narrative ("quand j'avais…", "depuis que j'ai…"), durations ("ans de…") and self-ages under 12 are excluded. Ages more than 2 years apart count as a conflict. Birth year combined with recording year is used only when the implied age range sits in one bracket. Coverage is low because few speakers state their age directly; most age information needs contextual reasoning (LLM stage).
- *Gender*: first-person grammatical agreement by the interviewee (audible forms weighted 2, spelling-only forms 1), plus interviewer address (madame/monsieur, "vous êtes née"). Address cues are downweighted when other people are present, because couples are often interviewed together. "mon mari/ma femme" is weak support only and never decides alone. The winner must reach a score of at least 2 and a 3:1 ratio over the other gender. This is grammatical/address evidence, a proxy, not gender identity. No stereotype-based inference.
- *Year*: present anchors ("on est en …"), past-tense year mentions, and era cues on all roles:
  - Recent: euros, internet, mobile phones, Sarkozy, post-2000 years.
  - Old: the bare "les événements de mai" (no year), marché commun, nouveaux francs, and a weak cue when three or more distinct years are named, all ≤1972.

## The 2010 contradiction (central caveat)

The task states the interview year is 1970 or 2005. The transcripts contradict a literal reading:
- **S035** interviewee, t=10.153 s: `donc euh on est en deux mille dix ça fait dix ans une dizaine d'années`
- **S163** interviewee, t=694.222 s: `comme on est en deux mille dix euh aujourd'hui …`
- **S192** interviewee, t=1338.419 s: `la dernière on est en deux mille dix`; also `je suis là depuis le quinze septembre euh deux mille huit`
- **S066**: `on est en deux mille on on on est en`. The utterance is truncated and ambiguous; flagged for review, not resolved.
- **Independent triangulation (birth year + stated age):**
  - S083 `je suis de cinquante-quatre` with `j'ai cinquante-cinq ans` → recorded 2009–10.
  - S091 born 1964, aged 46 → 2010–11.
  - The same method gives about 1969 for the old cohort: S120 born 1912, aged 57; S111 born 1878, about to turn 91.
  - Both waves line up near 1969 and about 2010.
- 24 interviews mention years after 2005, often as past events (S092 `depuis deux mille six je suis revenu`, S100 `depuis deux mille neuf`, S051 `je l'ai eue en décembre deux mille sept`). Some mentions are future plans (S071 `vont faire des conclusions en deux mille douze`), which the rules mark separately and do not use as a lower bound.

**Interpretation (hypothesis, unverified).** "2005" is most plausibly a cohort label for recordings made around 2008–2012, not a literal recording year. Likewise "1970" may cover around 1968–1971. Place names (Saint Marceau, Meung-sur-Loire: Orléans area) and the huma-num TRS DTD fit a two-wave Orléans sociolinguistic corpus. That is context, not proof. Because of this ambiguity:
- `cohort_hypothesis` gives the nearest cohort.
- `interview_year` (strict) is left blank whenever evidence contradicts the label as a literal recording year (8 interviews).
- `recording_year_lower_bound` and `out_of_domain_year_flag` are reported separately.

Organizers must confirm the label semantics before forced classification or scoring of the year field.

## Uncertainty and known limitations

- Regex cues have false positives and negatives. The manual spot-check covered all 18 age decisions and 10 random gender decisions, not the full set.
- The era cue weights were chosen by reasoning and by unsupervised co-occurrence checks, not tuned on labels. "les événements de mai" as an old-cohort cue rests on the observation that it never co-occurs with recent cues; it may partly reflect the interview protocol.
- 86 interviews have no cohort decision. Absence of evidence is not evidence for either cohort.
- Transcriber spelling of inaudible agreement (né/née) reflects the transcriber's perception.

## LLM pilot (5 interviews, run 2026-11-07, ≈ $2.72 of a $3 approval)

- **Interviews:** S035, S002, S163, S001, S010 on Opus 5.5 (adaptive thinking, medium effort; prompts extract_v1 / decide_v2).
- **Schema:** the first attempt hit an API 400 because nullable enums aren't accepted. The fix uses sentinel values, and the schema is now verified on 15 calls.
- **Grounding:** 0 errors over 11/11 chunks. Every quote is verbatim, with the matching role.
- **Agreement with rules_v2.4 (not accuracy):** no conflicts wherever both answered.
  - The LLM added 4 ages, 2 genders and 2 cohorts.
  - Recording years: 1969 for S001, S002, S010; 2010 for S035, S163.
- **Independent source check:** all 5 key claims are supported by the source. I first flagged S002's "married at 21" as an over-interpretation of `j'ai reçu ma dernière gifle à… vingt et un ans`. The next segment, 2117 (`avant de me marier j'en étais à quatre jours de me marier`), confirms it: my check was incomplete, not the model.
  - decide_v3 (stricter inference rules, re-checked for $0.22) marks S002's age as low confidence because the deciding quote reached the decision step only as a note. Bracket unchanged.
  - Lesson for manual review: read the neighbouring segments, not just the cited one.
- **Full-run estimate:** ≈ $74 on Opus 5.5 (≈ $37 with the Batch API), recalibrated from actual usage. Needs separate approval.

## LLM stage (implementation)

- **Prepared:** `src/llm_schema.py` (strict JSON schemas, local validator, verbatim/role/range grounding checks, a chunker that never truncates) and `src/llm_infer.py`.
- **Safe by default:** plan-only unless `--execute`, an approved budget and explicit IDs are given. Calls are cached on disk, so re-runs never repeat a call. The budget is checked against each call's worst-case cost. Provenance records model, effort, prompt SHA-256, chunks and run ID.
- **Estimated cost:** about $53 for the full corpus with Opus 5.5 (about $27 with the Batch API); about $1.66 for a 5-interview pilot.
- **Not run.** It needs (a) approval of the budget and (b) data-protection approval to send transcript text to the Anthropic API.

## Data protection

The transcripts contain personal narratives, first names, places and life histories. So far all processing has been local: no external uploads and no paid inference. Running the LLM stage sends transcript text to an external API. Do that only after the data owner's permission and a data-protection review: check the provider's retention terms and whether the corpus licence covers it. Evidence quotes in the outputs contain raw transcript text; treat output files with the same access controls as the corpus.

## Evaluation

Not performed. The frozen predictions can be scored only in a separately authorized step, with ground truth kept outside the workspace (`python -m src.evaluate …`). Report coverage and accuracy-when-answered separately, macro-F1 for gender and year, and age exact/adjacent-bin accuracy. Score the year field under both readings: literal and cohort.
