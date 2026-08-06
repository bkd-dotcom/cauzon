## What this adds

A new **`datahub-rca`** skill (plus a `catalog-rca` slash-command wrapper) that
performs **path-grounded root-cause analysis** for data incidents.

## How this differs from `datahub-lineage`

Worth addressing directly, because `datahub-lineage`'s description already lists
`"root cause"` among its triggers and the `using-datahub` routing table currently
sends root-cause requests there.

`datahub-lineage` **traverses** the graph — it answers "what feeds into X" and
"what breaks if I change X". That is the right tool for impact analysis, and this
skill does not duplicate it.

`datahub-rca` **adjudicates** the graph. Traversal tells you which upstream assets
exist; it does not tell you which one is to blame, and it has no way to decline.
This skill adds the three things that turn a dependency walk into a diagnosis:

1. **Ranking** across multimodal signals — freshness lag, volume anomaly, schema
   change, key uniqueness — rather than presenting every upstream equally.
2. **A proof gate.** A candidate is accepted only once its lineage path back to
   the symptom is reconstructed from real edges, with the transform SQL that
   carried the fault. A high-scoring asset with no path is rejected outright. This
   is the part traversal cannot express: the ability to say *no*.
3. **Write-back and read-back.** The dossier is persisted with `save_document`,
   the culprit tagged, and prior dossiers for the same asset retrieved with
   `search_documents` — so a repeat failure is recognised as a pattern rather than
   investigated from scratch.

A useful way to see the split: the lineage skill would happily report a stale,
schema-changed upstream as the likely culprit. This skill checks whether a path
to the symptom exists first, and drops the suspect when it does not.

Because of the overlap in phrasing, this PR also **updates the `using-datahub`
routing table** so "why did X break" routes here while "what depends on X" stays
with `datahub-lineage`. Without that, the new skill is unreachable in practice.

## Why it's useful

"Why did this dashboard break?" is a daily fire drill for data teams. Existing
observability alerts you *that* something broke; this skill localizes *why*, by
graph traversal, and shows its work. Because the proof path and the transform SQL
are part of the output, the diagnosis is auditable by whoever reads it next
instead of being taken on trust.

## Design principle: no ungrounded diagnosis

Drawn from recent root-cause-analysis research on path-grounded diagnosis: a
ranking is a hypothesis; a reconstructed lineage path plus the transform SQL is
proof. Only proof is written back to the shared catalog. When nothing can be
grounded, the skill escalates to a human rather than guessing — a wrong finding
written into a catalog everyone reads is worse than no finding, because the next
person inherits it as fact.

Where the transform SQL cannot be retrieved — common, since query history is
often absent — the skill reports the path as proven and the transform as
unavailable, rather than silently treating a partial proof as a complete one.

## Contents

- `skills/datahub-rca/SKILL.md` — the skill (standard frontmatter, expert voice)
- `skills/datahub-rca/README.md`
- `skills/datahub-rca/references/rca-signals-reference.md` — signal heuristics
- `skills/datahub-rca/references/grounding-reference.md` — the proof rules
- `skills/datahub-rca/templates/incident-dossier.template.md`
- `skills/datahub-rca/evaluations/` — two evaluations: the happy path, and one
  that specifically checks the skill rejects a suspect it cannot connect
- `commands/catalog-rca.md` — slash-command wrapper
- `skills/using-datahub/SKILL.md` — routing-table row (see above)
- `README.md` — skill listed alongside the existing catalog skills

## Testing

- `pre-commit run --all-files` passes (prettier, markdownlint, ruff).
- The skill relies only on standard MCP tools (`search`, `get_lineage`,
  `get_lineage_paths_between`, `get_entities`, `list_schema_fields`,
  `get_dataset_queries`, `search_documents`, `save_document`, `add_tags`,
  `update_description`) and works across Claude Code, Cursor, Codex, Copilot,
  Gemini CLI, and Windsurf.
- The technique is implemented and exercised end to end in a reference agent,
  including against a live `datahub docker quickstart` — the write-backs were
  read back out of the running catalog to confirm they landed. Happy to link the
  repository if that is useful context for review.

Built during **Build with DataHub: The Agent Hackathon**.
