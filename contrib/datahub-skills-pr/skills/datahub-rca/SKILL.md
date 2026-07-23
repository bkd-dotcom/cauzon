---
name: datahub-rca
description: |
  Use this skill when the user reports a data incident and wants to know WHY it happened — a dashboard showing wrong numbers, a failing freshness or volume assertion, an unexpected drop or spike, a broken pipeline. Triggers on: "why did X break", "root cause of X", "what caused this incident", "why is X stale", "why did the numbers drop", "diagnose this failing assertion", "investigate this data incident". This skill performs PATH-GROUNDED root-cause analysis: it walks lineage upstream, ranks candidate culprits from multimodal signals, and only accepts a root cause when it can reconstruct a verifiable lineage path to the symptom — then writes the incident dossier back to the catalog.
user-invocable: true
min-cli-version: 1.5.0.1rc1
allowed-tools: Bash(datahub *)
---

# DataHub Root-Cause Analysis

You are an expert DataHub incident investigator. Your role is to take a data
incident — a failing assertion, a stale table, a dashboard with wrong numbers —
and find its **root cause**, backed by a **verifiable lineage path**.

The guiding principle, drawn from recent root-cause-analysis research
(e.g. path-grounded diagnosis / "no ungrounded diagnosis"): **never blame a
table you cannot connect to the symptom with real lineage evidence.** A ranking
is a hypothesis; a reconstructed path + the transform that carried the fault is
proof. Only proof gets written back.

---

## Multi-Agent Compatibility

This skill works across coding agents (Claude Code, Cursor, Codex, Copilot,
Gemini CLI, Windsurf). Everything below relies only on standard DataHub MCP
tools and/or the `datahub` CLI, both available across agents.

---

## The five-phase workflow

### 1. Detect — establish the symptom

Resolve what actually broke into a concrete dataset URN.

- If given a natural-language complaint ("revenue dashboard looks wrong"), use
  **search** to find the affected asset.
- If given a failing assertion, read it. Note the assertion type
  (FRESHNESS / VOLUME / SCHEMA / SQL / FIELD) — it tells you which signals
  matter most downstream.

### 2. Scope — pull the minimal upstream subgraph

Call **get_lineage** with `upstream=true` and `max_hops=3` on the symptom. Do
not fan out wider than needed; a compact subgraph keeps the diagnosis focused
and cheap. Record each upstream node and its hop distance.

### 3. Hypothesize — rank candidates from multimodal signals

For each upstream node, gather evidence with **get_entities** (and
**list_schema_fields** where a schema change is suspected) and score these
signals:

| Signal | How to detect | Weight |
| --- | --- | --- |
| Freshness lag | freshness exceeds the expected SLA | high |
| Volume anomaly | row-count delta ≥ 20% vs baseline | medium |
| Schema change | columns added / removed / retyped recently | high |
| Recent query change | the defining transform in **get_dataset_queries** changed recently | medium |

**Heuristic that matters most:** the true root cause is usually the node
*furthest upstream* that still carries a strong signal — the origin, not the
intermediate victim that merely inherited the problem. Break ties toward greater
upstream distance.

### 4. Prove — accept only a verifiable path (the critical step)

For your top candidate, call **get_lineage_paths_between**
(`source` = symptom, `target` = candidate).

- If **no path** is returned, **reject the candidate** and move to the next one.
  Do not report an ungrounded cause.
- If a path exists, use **get_dataset_queries** along the path to identify the
  transform SQL that carried the fault downstream. The edge list + that SQL is
  your proof.

Only a candidate with a reconstructable path is accepted as the root cause.

### 5. Write back — persist the diagnosis so it's inherited

Once you have a grounded root cause, contribute it back to the graph:

- **save_document** — an incident dossier (symptom, evidence, proof path,
  transform SQL, recommended fix). Use the template in
  `templates/incident-dossier.template.md`.
- **add_tags** — tag the culprit `root-cause`.
- **update_description** — note the incident + link the dossier on the culprit.

If **no** candidate could be grounded, write nothing. Report that the cause
could not be verified and escalate to a human.

---

## Worked example

> "The revenue dashboard dropped 40% this morning and a volume assertion failed."

1. **Detect** — `search "daily_revenue"` → resolve the URN; the failing
   assertion is a VOLUME check.
2. **Scope** — `get_lineage(daily_revenue, upstream, 3)` → `trips_cleaned`,
   `raw_trips`.
3. **Hypothesize** — `get_entities` on each: `raw_trips` is 51h stale
   (SLA 24h) with −100% new rows. Strongest signal, furthest upstream → top
   candidate. `trips_cleaned` only inherited the staleness.
4. **Prove** — `get_lineage_paths_between(daily_revenue, raw_trips)` →
   verified path `raw_trips → trips_cleaned → daily_revenue`; capture the
   `COPY INTO raw_trips …` ingestion transform.
5. **Write back** — `save_document` dossier + `add_tags(raw_trips,
   [root-cause])` + `update_description`.

**Result:** "Root cause = `raw_trips` (ingestion stalled ~2 days ago). Proof:
`raw_trips → trips_cleaned → daily_revenue`. Fix: restart the `COPY INTO` job
and re-run downstream transforms once fresh data lands."

---

## Guardrails

- **No ungrounded diagnosis.** If you cannot reconstruct the path, say so.
- **Prefer the origin.** Don't stop at the first anomalous node; the fault
  usually starts further upstream.
- **Write back only when grounded.** The catalog is shared truth — never
  pollute it with a guess.

See `references/rca-signals-reference.md` for detailed signal heuristics and
`references/grounding-reference.md` for the path-verification rules.
