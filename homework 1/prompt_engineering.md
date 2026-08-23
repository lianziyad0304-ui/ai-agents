# Prompt Engineering — Homework 1

While building the multi-expert agent system, I experimented with several
prompt engineering techniques. Below are the three that had the clearest,
most observable effect on the model's output.

## 1. Few-Shot Examples

Each expert's configuration in `llm_roles` includes a `few_shot_examples`
field — a concrete example of a correctly-formatted response, not just a
description of what a correct response should look like. For example, the
Database Read Expert's example shows a full, real SQL query answering a
sample question, and the Database Write Expert's example shows a complete
Python snippet, including the exact `existing = db.query(...)` /
`if existing: ... else: ...` pattern and the exact `outcome = "..."`
assignment.

**Effectiveness:** This was one of the most reliable techniques I tested.
When an expert had a full, realistic example, its output consistently
matched that structure — the Write Expert, for instance, reliably produced
the `existing = db.query(...)` check-before-insert pattern and assigned
`outcome` correctly almost every time, because it had literally seen that
exact shape once already. Telling the model *"call db.insertRows and end
with an outcome variable"* in prose alone would likely have been followed
far less consistently than showing it done once.

## 2. Strict Output-Format Constraints

The `specific_instructions` field for each expert enforces a narrow,
unambiguous output format — e.g. the Read Expert is told *"Respond with a
single valid SQLite SELECT query only. No markdown, no explanation — SQL
only,"* and the Orchestrator is told to respond with *"a Python list of
strings, each an exact call in the form
`handle_ai_chat_request(role="...", message="...")"`.*

**Effectiveness:** This worked well for the scenarios the instructions
explicitly anticipated (read, write, and compound read-then-write
requests). Its limits became clear, however, when I tested a request the
instructions never covered — asking the Write Expert to *delete* a skill.
Since "delete" was never mentioned anywhere in its instructions or
examples, the model didn't refuse; instead it improvised a workaround
using `insertRows` with a `None` skill level, which failed with a
database constraint error. This showed me that strict formatting
constraints control *how* the model responds, but they don't stop it from
attempting something entirely outside its intended scope — the model will
try to satisfy the request format even when the underlying task doesn't
fit the tools it's been given.

## 3. Role Prompting via a Shared Master Template

Instead of writing four separate, unrelated system prompts, I built one
Jinja2 `MASTER_TEMPLATE` that every expert renders through, with each
expert supplying its own `role`, `domain`, `specific_instructions`,
`background_context`, and `few_shot_examples`. This means the *only*
difference between "Database Read Expert," "Database Write Expert,"
"Content Expert," and "Orchestrator" is the data plugged into that one
template — the underlying model (`gpt-4o-mini`) is identical in every
case.

**Effectiveness:** This was the clearest demonstration of how much a
prompt's framing shapes output, independent of the model itself. The
exact same model produced SQL in one call, executable Python in another,
plain natural-language text in a third, and a structured Python list plan
in a fourth — purely because each call opened with a different role
("You are a Database Read Expert, an expert in...") and different
supporting context. It also made the system much easier to extend: adding
a fifth expert would only require a new row in the `llm_roles` table, not
new code in `llm.py`.

## An additional observation: prompt *cleanliness* matters as much as content

While debugging, I discovered that a CSV encoding bug had corrupted the
em dashes (`—`) in the Write Expert's `background_context` into garbled
characters (`â€”`) because the file was being read without an explicit
`utf-8` encoding on Windows. Once that was fixed, the Write Expert's
responses became noticeably more reliable. This wasn't a wording or
technique problem — it was a reminder that a prompt engineered carefully
in content can still fail if the text delivered to the model isn't clean,
which is easy to overlook when focusing only on what a prompt *says*
rather than how it's actually transmitted.