# Cauzon — hackathon refinement design

**Date:** 2026-08-06
**Submission deadline:** 2026-08-10 17:00 EDT (Build with DataHub: The Agent Hackathon)

## Organizing principle

Cauzon lives on one sentence: **every root cause, proven from the source.** Every
change below must strengthen that claim. Work that only decorates gets cut first.

Two consequences:

- Where the code does not yet honor the claim, that is a correctness bug, not a
  polish item. It is fixed first.
- Where an artifact cannot be fully proven, it must **state its own grounding
  level** rather than overclaim.

## Verified research inputs

Hackathon rules (`datahub.devpost.com`), confirmed 2026-08-06:

| Requirement | Status today |
| --- | --- |
| Demo video under 3 minutes, public on YouTube/Vimeo | missing |
| Project URL with easy access to test functionality (hosted app preferred) | missing |
| Public repo, Apache-2.0 detectable in GitHub About section | license file present; About section unverified |
| Text description of features, functionality, technologies, data | missing |
| `examples/` folder of sample outputs (optional) | present |

Judging criteria: Use of DataHub (contributing back to the graph explicitly
favored), Technical Execution, Originality, Real-World Usefulness, Submission
Quality. Bonus for meaningful open-source contribution to DataHub.

DataHub MCP Server tool inventory verified against `docs.datahub.com`. All nine
tools `datahub_client.py` calls exist. Mutations require
`TOOLS_IS_MUTATION_ENABLED=true` (mcp-server-datahub v0.5.0+).

`datahub-project/datahub-skills` conventions verified by direct clone:
`SKILL.md` frontmatter (`name`, block-scalar `description`, `user-invocable`,
`min-cli-version`, `allowed-tools`), `evaluations/*.json` shape, and the
single-bundled-plugin `marketplace.json` all match what `contrib/` already ships.
Conventional-Commit PR titles are CI-enforced; pre-commit runs prettier,
markdownlint-cli2, and ruff.

## A. Agent core — make the central claim true

### A1. Grounding becomes a level, not a boolean

`agent.py:209` sets `verified = bool(edges)`, but `agent.py:178` and README:38
both promise a path **and** transform SQL. Replace the boolean with a ladder:

| Level | Meaning |
| --- | --- |
| `PATH_AND_TRANSFORM` | Lineage edges reconstructed **and** transform SQL captured on the causal edge |
| `PATH_ONLY` | Lineage edges reconstructed, no SQL retrievable |
| `UNGROUNDED` | No path — hypothesis rejected |

Write-back is permitted at `PATH_ONLY`, but the dossier and UI label their own
grounding level and confidence drops accordingly.

A strict SQL requirement was considered and rejected: real DataHub instances
frequently lack query history, so it would make the tool useless in production
while looking rigorous in the mock. An artifact that declares its own epistemic
status is both more honest and more useful. README:38 is corrected to match.

### A2. Implement the origin reasoning the code only claims

`agent.py:143` documents comparing a node's freshness lag against its downstream
to locate the origin. The code instead adds `0.25 × hops`.

Replace with the actual causal rule: a node scores as origin when it carries the
signal **and its own upstreams do not** — the furthest point at which the fault
appears. This states a real argument ("nothing above this is broken"), makes
code match comment, and generalizes beyond the two mocks that currently make the
hops heuristic accidentally correct.

### A3. Confidence must be derivable

Replace `0.6 + 0.1 × len(signals)` with an explicit product of three named
factors, each individually reportable so the UI can show the breakdown:

```
confidence = grounding_factor × signal_factor × origin_factor

grounding_factor: PATH_AND_TRANSFORM 1.0 | PATH_ONLY 0.75 | UNGROUNDED 0.0
signal_factor:    0.55 + 0.15 × distinct_signals, capped at 1.0
origin_factor:    1.0 if no upstream carries the signal (true origin)
                  0.7 if an upstream also carries it (may be inherited)
```

Every number the UI shows traces to one of these factors.

### A4. Hybrid reasoning layer (`agent/cauzon/reasoner.py`)

The README cites DeepRoot (ICML 2026) — *separate grounding from reasoning to cut
hallucination*. This implements that citation rather than working around it.

Deterministic code owns grounding and the proof gate. An optional Claude
(`claude-sonnet-5`) layer owns explanation: it writes dossier narrative and
explains why the top candidate beat the runner-up.

Structural guarantees, enforced by construction and by test:

- It receives only already-grounded facts.
- It cannot set `grounded`, choose the root cause, or emit a URN.
- With no API key it falls back to templates. Existing tests stay green either way.

### A5. Third scenario and a decoy

A third fault type (duplicate-row fanout from a bad join) proves the signal
framework is not hardcoded to two demos.

The decoy matters more: a node with strong signals but **no lineage path**, so
the *"rejected — cannot ground"* branch becomes visible during the demo. Cauzon's
best argument currently never fires on screen.

### A6. Recurring-incident detection

`save_document` writes dossiers that are never read back. Wire
`search_documents` / `grep_documents` to find prior Cauzon dossiers for the same
asset, so a diagnosis can report *"third stall in 30 days"* and escalate its
recommendation from "backfill" to "fix the ingestion schedule."

This is the strongest available answer to the "contributing back to the graph is
favored" criterion: the write-back stops being a one-way gesture and the
knowledge compounds across runs.

### A7. Owner resolution

README:39 promises the write-back phase notes the owner; the code does not. Read
ownership for the culprit and include it in the dossier and UI so the diagnosis
routes to a person.

### A8. Fix SQL instead of prose

`_recommend_fix` returns prose. It becomes a structured `RecommendedFix` carrying
prose **and** a concrete, copyable SQL/CLI action derived per signal type:

- `SCHEMA_CHANGE` — a corrected `CREATE OR REPLACE` built from the captured
  transform SQL with the renamed column substituted, using `list_schema_fields`
  to confirm the new column name exists
- `FRESHNESS_LAG` — the backfill/re-run command for the culprit, plus the
  downstream transforms to replay in dependency order
- `VOLUME_ANOMALY` / fanout — a diagnostic duplicate-detection query over the
  join keys

Derivation is deterministic from captured facts, so it works identically on the
mock and MCP backends. `draft_sql_for_tables` is deliberately **not** used: it
would put an unverifiable generated statement inside a tool whose entire pitch is
that it only shows what it can prove.

### A9. Tests for all of the above

Including negative tests: the reasoner cannot promote an ungrounded diagnosis;
`PATH_ONLY` is labeled as such; the decoy is rejected.

## B. Frontend rebuild — the proof path becomes the product

Next 16 + React 19 + Tailwind 4 with shadcn primitives, rebuilt in `frontend/`.
`next-app-template/` is deleted (its HeroUI aesthetic is recognizable and it
ships navbar/blog/docs/about scaffolding that would need stripping).

**Centerpiece: a custom SVG lineage DAG**, animated against the live trace —
nodes appear during `scope`, score during `hypothesize`, the proof path
illuminates and rejected candidates visibly strike out during `prove`. This is a
visual argument for the thesis, not an ornament, and it is the one thing that
makes a sub-3-minute video memorable.

Supporting surfaces:

- Streaming phase timeline with real phase semantics
- Evidence cards showing actual numbers (`51h vs 24h SLA`), not prose
- Proof panel: path, marked causal edge, grounding-level badge, transform SQL
- Write-back receipts showing the literal DataHub mutations
- Recurrence panel when A6 finds prior dossiers

A full typed API contract replaces the current `any` usage, matched to the Python
models. Visual direction comes from the frontend-design skill so the result does
not land as another dark-blue dashboard.

### B1. Client-side mock mode

The rules reward a hosted app judges can test, but the backend is Python and the
judging window is short. So the frontend ships a mock investigation that runs
entirely client-side, letting the deployed site perform a full streamed
investigation with zero install.

The real FastAPI backend remains for local use and live DataHub. Mock mode is a
demo affordance, not a second source of truth: it replays the same phase sequence
and shapes.

## C. Landing page

Rebuilt inside the same Next app — `/` landing, `/investigate` app — so there is
one deploy and one shareable URL. The hero carries the thesis, shows the
proof-path concept visually, and links to the demo, the repo, and the OSS PR.

## D. Submission assets

Now requirements rather than nice-to-haves.

- CI: GitHub Actions running pytest plus frontend typecheck and build
- `demo/`: 3-minute video script and storyboard, plus a CLI transcript (recording
  the video is the user's job)
- Devpost description draft covering features, functionality, technologies, data
- Architecture diagram
- GitHub About: description, topics, and confirmation GitHub detects Apache-2.0
- README restructured to lead with thesis and a visual; configuration moves down
- Fix the stray Russian word `что` in `examples/live-proof/README.md`

### D1. Actually open the OSS PR

`contrib/` is currently *ready-to-PR*. Opening it converts a claim into a fact
and triggers the bonus criterion. Two blockers found during research must be
fixed first:

- `skills/using-datahub/SKILL.md` already routes *"root cause"* to
  `/datahub-lineage`, whose own description claims *"find root causes."* The PR
  must update that routing row.
- The PR body must explicitly differentiate `datahub-rca` from `datahub-lineage`
  — grounding, proof gate, and dossier write-back versus lineage traversal —
  or it reads as a duplicate and gets rejected.

Opening the PR requires the user's GitHub account and is an outward-facing
action, so it is prepared fully and confirmed before pushing.

## Sequencing

A → B → C → D. A reshapes the data B renders; B's components feed C.

Risk note: this is a large body of work. The order is chosen so that anything
that slips is a D nice-to-have rather than pitch-critical. Video recording,
Devpost submission, and the survey opt-in remain the user's actions.

## Success criteria

1. No claim in the README or in code comments that the code does not honor.
2. `pytest` green, including new negative tests for grounding.
3. A judge can open one URL and watch a full grounded investigation, including a
   rejected candidate, without installing anything.
4. Every number shown in the UI traces to a stated reason.
5. The OSS PR is open, or prepared and awaiting the user's confirmation.
