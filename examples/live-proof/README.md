# Live Write-Back Proof

This folder contains **raw evidence, captured directly from a running
`datahub docker quickstart`**, that Cauzon performed a grounded root-cause
investigation and wrote its findings back into the live catalog.

Everything here was pulled from DataHub's own APIs *after* the agent ran —
independent confirmation that the writes actually landed, not just that the agent
claimed success.

## How it was produced

```bash
# 1. plant a demo lineage graph in live DataHub
python scripts/ingest_demo_lineage.py
# 2. run Cauzon end-to-end with write-back against the live instance
python scripts/run_live_writeback.py
# 3. capture the aspects back out of DataHub (the files in this folder)
```

## The incident

`daily_revenue` reported a 40% volume drop (a volume assertion failed). Cauzon
walked lineage upstream, ranked candidates, and identified the **origin**:
`raw_trips` — ingestion stalled ~2 days ago (freshness 51h vs 24h SLA, −100% new
rows). The intermediate `trips_cleaned` merely inherited the staleness.

## The artifacts

| File | What it proves |
| --- | --- |
| [`05-agent-run-transcript.txt`](./05-agent-run-transcript.txt) | The full live run: detect → scope → hypothesize → prove → writeback, against `http://localhost:8080`. |
| [`04-upstreamLineage.jsonl`](./04-upstreamLineage.jsonl) | The lineage chain Cauzon traversed is **real** in DataHub: `daily_revenue ← trips_cleaned ← raw_trips`. |
| [`01-globalTags-raw_trips.json`](./01-globalTags-raw_trips.json) | Cauzon **tagged the culprit** — `raw_trips` now carries `urn:li:tag:root-cause` and `urn:li:tag:cauzon-diagnosed`. |
| [`02-description-raw_trips.json`](./02-description-raw_trips.json) | Cauzon **updated the description** with the incident note + a link to the dossier document. |
| [`03-dossier-document.json`](./03-dossier-document.json) | Cauzon **created a Document** in DataHub — the full RCA dossier (title, evidence, proof path). |

## Verified write-backs (summary)

**Tags on `raw_trips`** (`01-globalTags-raw_trips.json`):

```json
{
  "globalTags": { "value": { "tags": [
    { "tag": "urn:li:tag:root-cause" },
    { "tag": "urn:li:tag:cauzon-diagnosed" }
  ] } }
}
```

**Description on `raw_trips`** (`02-description-raw_trips.json`):

> ⚠️ Cauzon identified this as the root cause of incident 'daily_revenue is 40%
> below expected volume'. See dossier `urn:li:document:shared-…`.

**Dossier document** (`03-dossier-document.json`) — title
`[Cauzon] RCA: daily_revenue is 40% below expected volume`, containing the
grounded root cause, evidence, and the verifiable proof path
`raw_trips → trips_cleaned → daily_revenue`.

## Why this matters

The DataHub judging criteria explicitly reward submissions that *"go beyond
reading metadata and contribute back to the graph."* This is that, verified
end-to-end against a real instance: Cauzon doesn't just diagnose — it writes the
diagnosis back so the next person or agent inherits it.
