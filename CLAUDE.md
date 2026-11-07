# Claude Code research guardrails

Read `PROMPT.md`, `TASKS.md`, and `JOURNAL.md` before doing anything. Work test-first and record changes. Never open any Ground Truth, label, solution or evaluation answer file before predictions have been frozen; store them outside the workspace. Do not infer age/gender from stereotypes or assign speech in overlapping turns to just one person. Acknowledge uncertainty. The year set {1970, 2005} is a **hypothesis**: S035 contains a self-referential 2010 anchor, so inspect contradictory evidence before treating the classification as complete.

No blind repeated API calls: estimate costs and get approval before batch LLM inference. Do not upload raw interview data to an external service without permission and appropriate data protection review.
