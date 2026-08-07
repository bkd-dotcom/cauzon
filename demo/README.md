# Demo video — script and shot list

The hackathon requires a public video **under 3 minutes**. This script runs
about 2:55 at a normal speaking pace — close to the limit, so trim rather than
rush if a take runs long.

**One idea to land:** Cauzon rejects the most suspicious asset in the graph
because it cannot prove a path to it. Everything else is supporting detail. If a
shot does not serve that, cut it.

## Before recording

```bash
# 1. Backend (optional — the UI replays recorded runs without it, but a live
#    backend is more convincing on camera).
uvicorn backend.main:app --port 8000

# 2. Frontend
cd frontend && npm install && npm run dev     # http://localhost:3000
```

Open `http://localhost:3000/investigate`, pick **daily_revenue is 40% below
expected volume**, and *do not* press Investigate — the reveal is the demo.

Recording notes: 1280×800 or 1920×1080, browser zoom at 110% so the graph labels
are legible after compression, and hide bookmarks and notifications.

## Shot list

| # | Time | Shot | Say this |
| --- | --- | --- | --- |
| 1 | 0:00–0:20 | Landing page hero, scrolled so the graph replays | "A volume assertion just failed on `daily_revenue`. Every observability tool can tell you that. None of them can tell you *why*, and prove it." |
| 2 | 0:20–0:35 | Scroll to "A ranking is a hypothesis. A path is proof." | "Cauzon is a root-cause agent for DataHub. Its whole claim is that it will not blame an asset it cannot connect to the symptom with real lineage." |
| 3 | 0:35–0:50 | `/overview` — triage inbox, then click `Investigate →` on `daily_revenue` | "You don't start knowing which asset to look at. So it opens on the queue: every open incident, sorted by how far past its *own* SLA each one is, with what's downstream of it. Top of the list is `daily_revenue`. Let's take it." |
| 4 | 0:50–1:15 | Graph animating — nodes appear, scores grow | "It pulls the upstream subgraph, then ranks candidates on freshness, volume, schema change and key uniqueness. Watch the scores. `marketing_spend` is winning — it's two days stale, it lost 88% of its rows, and a column was renamed four hours ago." |
| 5 | 1:15–1:35 | **The rejection.** Severed connector, strikethrough | "And Cauzon throws it out. There is no lineage edge from `marketing_spend` to the symptom, so however suspicious it looks, the claim cannot be grounded. A ranking is a hypothesis. This is the gate." |
| 6 | 1:35–1:50 | Jade spine draws to `raw_trips` | "The real origin is `raw_trips`, two hops up. Cauzon proves it: path reconstructed from real edges, plus the transform SQL that carried the fault downstream." |
| 7 | 1:50–2:05 | Confidence panel | "Confidence isn't a magic number. It's grounding times signal strength times origin purity, and every factor states its own reason." |
| 8 | 2:05–2:25 | Scroll: blast radius, then missing guardrail | "It doesn't stop at the cause. Three downstream assets inherit this data and none of them is alerting — somebody is reading those right now. And it read its own prior dossiers back: this asset has stalled twice before, so instead of 'backfill this window' it proposes the freshness check that would have caught it 27 hours earlier, at the source." |
| 9 | 2:25–2:40 | Write-back receipts, then the DataHub UI showing the `root-cause` tag | "Then it files everything back: the dossier, the tag, the owner. The next person inherits the answer instead of re-deriving it." |
| 10 | 2:40–2:55 | `contrib/datahub-skills-pr/` or the open PR | "And the same technique is contributed upstream as a DataHub Skill, so any MCP-connected agent can do path-grounded RCA. Every root cause, proven from the source." |

## If you have less time

Cut shot 7, and trim shot 8 to the blast-radius line only. Shots 4→5→6 are
the demo; the rest is framing.

## If you have room

The shot list runs 2:55 against a 3:00 limit, so these are trades rather than
additions. Both are on `/overview`, so they cost no navigation.

**Catalog map** (~12s, trade against shot 7). Scroll down from the inbox.

> "And the same view shows the whole catalog at once, laid out so every asset
> draws to the right of what it depends on. Three separate incidents — and you
> can see they share an upstream."

Worth it if the recording feels abstract: it is the one frame where "the problem
is upstream" is a direction you can point at rather than an argument.

**Zone map** (~10s, needs the live catalog selected, trade against shot 10).

> "This is the live half — real assets, real freshness, from NYC Open Data. The
> stale one is the zone lookup table, and these are the 263 zones it defines.
> Every trip record downstream resolves its pickup through one of these. Stale
> geography, not just a stale row count."

Strongest if the audience is skeptical that anything here is real: the geometry
is fetched from the same dataset the incident is about.

## Terminal alternative

If screen-recording the browser is awkward, the CLI shows the same reasoning and
is easier to read on camera:

```bash
PYTHONPATH=agent python -m cauzon.cli --no-writeback
```

`demo/cli-transcript.txt` is a recorded run of exactly that, including the
rejection line — useful for a thumbnail or as a fallback if a recording fails.

## Checklist before submitting

- [ ] Under 3:00, uploaded to YouTube or Vimeo, visibility **public**
- [ ] Captions or clear audio — judges may watch muted
- [ ] Project URL in the submission points at the deployed demo
- [ ] Repo is public and GitHub's About panel shows the Apache-2.0 license
- [ ] Devpost description pasted from `demo/SUBMISSION.md`
- [ ] Feedback survey opted into (it's a separate $50 × 10 prize pool)
