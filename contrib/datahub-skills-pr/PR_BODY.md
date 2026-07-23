## What this adds

A new **`datahub-rca`** skill (plus a `catalog-rca` slash-command wrapper) that
performs **path-grounded root-cause analysis** for data incidents.

The existing `datahub-lineage` skill can *trace* dependencies and the
`datahub-quality` skill can *find* unhealthy assets. This skill composes those
capabilities into something neither does on its own: given a failing assertion
or a symptom (stale table, wrong dashboard), it walks lineage upstream, ranks
candidate culprits from multimodal signals (freshness, volume, schema, query
change), and — critically — **only accepts a root cause when it can reconstruct
a verifiable lineage path** from the symptom to the cause, capturing the
transform SQL that carried the fault. It then writes the incident dossier back
to the catalog so the next person or agent inherits the finding.

## Why it's useful

"Why did this dashboard break?" is a daily fire drill for data teams. Existing
observability alerts you *that* something broke; this skill localizes *why*, by
graph traversal, and shows its work.

## Design principle: no ungrounded diagnosis

Inspired by recent root-cause-analysis research (path-grounded diagnosis): a
ranking is a hypothesis, a reconstructed lineage path + transform SQL is proof.
Only proof is written back to the shared catalog. If nothing can be grounded,
the skill escalates to a human instead of guessing.

## Contents

- `skills/datahub-rca/SKILL.md` — the skill (standard frontmatter, expert voice)
- `skills/datahub-rca/README.md`
- `skills/datahub-rca/references/` — signal heuristics + grounding rules
- `skills/datahub-rca/templates/incident-dossier.template.md`
- `skills/datahub-rca/evaluations/diagnose-volume-drop.json`
- `commands/catalog-rca.md` — slash-command wrapper

## Testing

- `pre-commit run --all-files` passes (prettier, markdownlint, ruff).
- The skill relies only on standard MCP tools (`search`, `get_lineage`,
  `get_lineage_paths_between`, `get_entities`, `list_schema_fields`,
  `get_dataset_queries`, `save_document`, `add_tags`, `update_description`) and
  works across Claude Code, Cursor, Codex, Copilot, Gemini CLI, and Windsurf.

Built during **Build with DataHub: The Agent Hackathon**.
