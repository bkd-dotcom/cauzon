# Devpost submission text

Paste the sections below into the corresponding Devpost fields. Keep the
tagline and the first paragraph intact — they carry the one claim the project is
making.

---

## Tagline

Every root cause, proven from the source — a path-grounded RCA agent for DataHub
that refuses to blame an asset it cannot connect to the symptom.

## Challenge track

Agents that do real work.

---

## What it does

Cauzon investigates data incidents on DataHub. When an assertion fails, it walks
the lineage graph upstream, ranks candidate culprits from multimodal signals, and
names a root cause **only when it can reconstruct the exact lineage path**
connecting that cause to the symptom. Then it files the dossier back into the
catalog, tags the culprit, and notes the owner.

The point is the refusal. Every anomaly detector produces a ranked list of
suspects; the failure mode is a confident, well-scored, wrong answer, and a
diagnosis nobody can audit is worse than no diagnosis because someone acts on it.
Cauzon separates ranking from proving and lets the second step veto the first.

The demo makes that visible. In the freshness scenario, `marketing_spend` is the
most suspicious asset in the graph — two days stale, 88% of its rows gone, a
column renamed four hours ago — and it scores highest at 8.0. Cauzon rejects it,
because no lineage edge connects it to the symptom. The real origin is
`raw_trips` at 5.0, two hops upstream, and that one it proves.

## How it works

Five phases against the DataHub MCP server, each streamed to the UI as it
happens so the reasoning is auditable while it runs:

1. **Detect** — pick up a failing assertion (`search`, incidents)
2. **Scope** — pull the minimal upstream subgraph, three hops (`get_lineage`)
3. **Hypothesize** — rank on freshness lag, volume anomaly, schema change and
   key uniqueness (`get_entities`, `list_schema_fields`). A node scores as the
   *origin* when it carries the fault and none of its own upstreams do — the
   causal argument, rather than ranking by hop distance
4. **Prove** — reconstruct the path from real edges and capture the transform SQL
   that carried the fault (`get_lineage_paths_between`, `get_dataset_queries`).
   No path, no diagnosis
5. **File** — write the dossier, tag the culprit, and read prior dossiers back
   (`save_document`, `add_tags`, `update_description`, `search_documents`)

**Grounding is a ladder, not a boolean.** A finding is `PATH_AND_TRANSFORM`,
`PATH_ONLY`, or `UNGROUNDED`, and it states its own rung. Requiring transform SQL
absolutely would look rigorous and be useless — real DataHub instances often have
no query history — so a path-only finding still writes back, at reduced
confidence, saying exactly what it could and could not prove.

**Confidence is derivable.** It is a product of three named factors — grounding
level, signal agreement, origin purity — each reported with its own reason, so
every number in the UI traces to something.

**The write-back is a loop.** Cauzon reads its own prior dossiers out of the
catalog with `search_documents`. On the third stall of the same ingestion job the
recommendation stops being "backfill this window" and becomes "the schedule is
the defect." The knowledge compounds instead of being re-derived.

## Grounded in current research

- **RCRank** (VLDB 2025) — multimodal ranking beats a single anomaly score
- **PAVE / OpenRCA 2.0** — the ungrounded-diagnosis problem: a correct cause with
  an unverified path is unacceptable
- **DeepRoot** (ICML 2026) — separate grounding from reasoning to cut
  hallucination. This is implemented literally: the proof gate is deterministic
  code, and the optional Claude layer only explains a verdict already settled. It
  receives nothing ungrounded, cannot reach any decision field, and its output is
  discarded if it invents a URN

## Technologies

Python agent core (framework-agnostic, no LLM required), FastAPI with a
WebSocket for the live trace, Next.js 16 / React 19 / Tailwind 4 frontend with a
hand-built SVG lineage diagram, DataHub MCP Server via `datahub-agent-context`,
and an optional Claude (`claude-opus-5`) narration layer that degrades to
deterministic templates.

## Data used

Two backends behind one interface. The **mock** backend ships three planted
scenarios and needs no infrastructure, which is what the deployed demo and the
test suite run against. The **MCP** backend talks to a real DataHub instance;
it has been verified end to end against `datahub docker quickstart` with the
`showcase-ecommerce` datapack, and `examples/live-proof/` contains the aspects
read back out of the running catalog afterwards — the tags, the updated
description, and the dossier document.

Three scenarios, each planting a fault a *different* signal has to catch:

| Scenario | Fault | Why it matters |
| --- | --- | --- |
| Freshness | Ingestion stalled two days ago, staleness propagates | Includes the ungroundable decoy that outranks the real cause |
| Schema change | A column rename silently breaks a downstream transform | Nothing is stale; no freshness or volume alert would fire |
| Join fanout | A dimension table gains duplicate keys, joins multiply | Nothing is stale and nothing changed shape — only key uniqueness finds it |

## Try it

The deployed app replays recorded runs of the real agent in the browser, so it
works with nothing installed. To run it against your own DataHub:

```bash
pip install -e ".[datahub]"
export CAUZON_DATAHUB_BACKEND=mcp
export DATAHUB_GMS_URL=http://localhost:8080
export DATAHUB_TOKEN=<personal access token>
uvicorn backend.main:app --port 8000
```

Write-back tools need the MCP server running with
`TOOLS_IS_MUTATION_ENABLED=true`.

## Open-source contribution

`contrib/datahub-skills-pr/` contains **`datahub-rca`**, a DataHub Skill that
teaches any MCP-connected agent to perform path-grounded RCA — the skill, a
signals reference, a grounding reference, a dossier template, evaluations, and a
slash-command wrapper, formatted to the conventions of
`datahub-project/datahub-skills`.

It is deliberately scoped against the existing `datahub-lineage` skill: that one
*traverses* lineage, this one *adjudicates* it — it adds the proof gate, the
grounding ladder, and the dossier write-back, and it updates the `using-datahub`
routing table so root-cause requests route to it rather than to plain lineage
traversal.

## What I'd do next

Learn the signal weights from resolved incidents instead of hand-tuning them;
support column-level lineage so the proof can name the column that broke rather
than the table; and file a DataHub *proposal* instead of a direct mutation when
the culprit sits in a governed domain.
