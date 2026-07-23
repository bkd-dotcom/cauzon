# Cauzon

**Every root cause, proven from the source.**

Cauzon is a path-grounded root-cause analysis agent for data incidents, built on
[DataHub](https://datahub.com). When a data-quality assertion fails or a
dashboard shows wrong numbers, Cauzon walks DataHub's lineage graph **upstream**,
ranks candidate culprits from multimodal signals, and returns a root cause
**only when it can prove the exact lineage path** connecting the cause to the
symptom. It then writes the incident dossier back into DataHub so the next
person — or agent — inherits the knowledge.

> Built for **Build with DataHub: The Agent Hackathon** — *Agents That Do Real Work*.

## Why Cauzon is different

Commercial data-observability tools **alert** you that something broke. They do
not autonomously **localize the cause** by traversing lineage — and they never
show you a *verifiable proof path*. Cauzon does both.

The design is grounded in 2025–2026 top-venue research:

- **RCAFlow** (AAAI 2026) — hierarchical multi-agent root-cause planning.
- **RCRank** (VLDB 2025) — multimodal ranking of root causes.
- **PAVE / OpenRCA 2.0** — the *ungrounded diagnosis* problem: a correct cause
  with an unverified path is unacceptable. Cauzon **rejects unprovable
  hypotheses** and refuses to write them back.
- **DeepRoot** (ICML 2026) — separate *grounding* from *reasoning* to cut
  hallucination.

## How it works — the investigation loop

| Phase | What Cauzon does | DataHub tools |
|-------|------------------|---------------|
| **Detect** | Pick up a failing assertion / incident | `search`, incidents |
| **Scope** | Pull the minimal upstream subgraph (≤3 hops) | `get_lineage` |
| **Hypothesize** | Rank culprits by freshness lag, volume anomaly, schema change | `get_entities`, `list_schema_fields` |
| **Prove** | Accept a cause **only** with a verifiable lineage path + transform SQL | `get_lineage_paths_between`, `get_dataset_queries` |
| **Write back** | Persist dossier, tag culprit, note owner | `save_document`, `add_tags`, `update_description` |

## Quickstart

### 1. Run DataHub locally (optional for the mock demo)

```bash
datahub docker quickstart
datahub init --username datahub --password datahub
datahub datapack load showcase-ecommerce
```

Cauzon ships with a **mock backend** containing a planted freshness fault, so you
can run the full app with **zero infrastructure**. Switch to a real DataHub
instance by setting `CAUZON_DATAHUB_BACKEND=mcp` and the MCP env vars.

### 2. Backend (the agent + API)

```bash
python3 -m pip install -e .           # installs fastapi, uvicorn, pydantic
uvicorn backend.main:app --port 8000  # http://localhost:8000
# or run the agent straight from the terminal:
PYTHONPATH=agent python3 -m cauzon.cli
```

### 3. Frontend (web + installable mobile PWA)

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

Set `NEXT_PUBLIC_CAUZON_API` if the backend isn't on `localhost:8000`.

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `CAUZON_DATAHUB_BACKEND` | `mock` | `mock` (planted-fault demo) or `mcp` (real DataHub) |
| `CAUZON_MOCK_SCENARIO` | `freshness` | `freshness` or `schema_change` (mock backend only) |
| `DATAHUB_GMS_URL` | `http://localhost:8080` | GMS endpoint (mcp backend) |
| `DATAHUB_TOKEN` | — | DataHub personal access token (mcp backend) |
| `CAUZON_CORS_ORIGINS` | `*` | Allowed CORS origins for the API |

### Using the real DataHub backend

```bash
pip install -e ".[datahub]"      # installs datahub-agent-context + acryl-datahub
export CAUZON_DATAHUB_BACKEND=mcp
export DATAHUB_GMS_URL=http://localhost:8080
export DATAHUB_TOKEN=<your personal access token>   # from DataHub Settings → Access Tokens
```

Write-back tools (`add_tags`, `update_description`, `save_document`) require the
MCP server to run with `TOOLS_IS_MUTATION_ENABLED=true`. The
`MCPDataHubClient` in `agent/cauzon/datahub_client.py` normalises every MCP
response into the same shape the mock returns, so the agent logic is identical
across backends.

**Verified live:** the MCP backend has been smoke-tested against a real
`datahub docker quickstart` with the `showcase-ecommerce` datapack loaded —
`search`, `get_entity`, `list_schema_fields`, `get_lineage`, and
`get_dataset_queries` all return real catalog data. Reproduce with:

```bash
python scripts/mcp_smoke_test.py
```

### End-to-end write-back against live DataHub (verified)

A full grounded investigation *with write-back* has been run against a live
instance. Reproduce:

```bash
# 1. plant a demo lineage graph (raw_trips -> trips_cleaned -> daily_revenue -> dashboard)
python scripts/ingest_demo_lineage.py
# 2. investigate the planted incident and write the results back
python scripts/run_live_writeback.py
```

This produced, on the live catalog:

- `globalTags` on `raw_trips` → `root-cause`, `cauzon-diagnosed`
- `editableDatasetProperties.description` → the incident note + dossier link
- a `Document` entity → the full RCA dossier (title, evidence, proof path)

Two robustness details worth noting, both handled by `MCPDataHubClient`:

- **Tag auto-creation** — DataHub rejects applying a tag whose entity does not
  exist, so `add_tags` emits a minimal `tagProperties` aspect first.
- **Graph-index-independent lineage** — the lineage *search* API depends on the
  graph index, which can lag (or stall on a constrained quickstart). When it
  returns nothing, Cauzon falls back to walking the durable `upstreamLineage`
  aspects directly, so RCA still works.

> Tip: if GMS on `:8080` looks unreachable, make sure no other local process is
> already bound to port 8080 before running `datahub docker quickstart`.

## Open-source contribution

`contrib/datahub-skills-pr/` is a ready-to-PR **DataHub Skill** (`datahub-rca`)
that teaches any MCP-connected agent (Claude Code, Cursor, Gemini CLI, …) to
perform path-grounded RCA. It is formatted to match the conventions of
[`datahub-project/datahub-skills`](https://github.com/datahub-project/datahub-skills)
(verified against their `datahub-lineage` skill + `CONTRIBUTING.md`). See
[`contrib/datahub-skills-pr/README.md`](./contrib/datahub-skills-pr/README.md)
for exact fork/PR steps — contributing it triggers the hackathon OSS bonus.

## Repository layout

```
cauzon/
├── LICENSE                    # Apache 2.0
├── pyproject.toml
├── agent/cauzon/              # the agent core (framework-agnostic)
│   ├── agent.py               # detect → scope → hypothesize → prove → writeback
│   ├── datahub_client.py      # MCP client + mock (planted-fault) backend
│   ├── models.py
│   └── cli.py
├── backend/main.py            # FastAPI + WebSocket live trace
├── frontend/                  # Next.js PWA (web + mobile)
├── contrib/datahub-skills-pr/ # ready-to-PR DataHub Skill (OSS bonus)
├── examples/                  # real Cauzon-generated incident dossiers
└── tests/                     # deterministic tests over the planted fault
```

## License

Apache-2.0. See [LICENSE](./LICENSE).
