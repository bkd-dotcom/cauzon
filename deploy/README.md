# Running Cauzon live

Three things can be live, and they cost very different amounts. Deploy them in
this order — each stage stands on its own, and the UI degrades rather than breaks
if a later stage is missing.

| Stage | What becomes true | Cost | Effort |
| --- | --- | --- | --- |
| 0. Static site | The website is up permanently | free | done |
| 1. Cloud Run backend | The **agent** really executes, streaming live | ~free | ~30 min |
| 2. GCE + DataHub | The **catalog** is a real DataHub | ~$35–50/mo | ~1–2 h |

**"Mock" describes the data source, not the agent.** `MCPDataHubClient` normalises
MCP responses into the same shape the mock returns, so the ranking, the origin
rule, the proof gate and the dossier are identical either way. Stage 1 alone gets
you a genuinely live agent; stage 2 makes the catalog real too.

The UI says which of these it is talking to, in the header — `Recorded agent run`,
`Live agent · demo catalog`, or `Live agent · real DataHub`. Don't remove that.
Being precise about what is and isn't proven is the product's whole argument;
overstating it in the product's own chrome would be self-refuting.

---

## Stage 1 — the agent on Cloud Run

Cloud Run fits this backend well: it is stateless (a fresh agent per request),
requests last about a second, and WebSockets are supported. Verified locally —
the image honours `$PORT`, binds `0.0.0.0`, and runs as a non-root user.

```bash
gcloud config set project YOUR_PROJECT
gcloud services enable run.googleapis.com artifactregistry.googleapis.com

# Build and deploy from source; Cloud Build picks up the root Dockerfile.
gcloud run deploy cauzon-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --min-instances 1 \
  --set-env-vars "CAUZON_CORS_ORIGINS=https://YOUR_USER.github.io"
```

Then point the frontend at it and redeploy Pages:

```bash
# frontend/.env.production, or a repo secret consumed by the Pages workflow
NEXT_PUBLIC_CAUZON_API=https://cauzon-api-XXXX.us-central1.run.app
```

Four flags worth understanding rather than copying:

- **`--min-instances 1`** keeps one instance warm. Without it a judge's first
  click waits on a cold start, and the frontend's 1.5s health-probe timeout will
  have already fallen back to replay — so the live backend would exist and never
  be seen. This is the flag that matters most.
- **`--timeout 300`** is the request ceiling, and a WebSocket counts as one
  request. Investigations take about a second; 300s is slack, not a target.
- **`--allow-unauthenticated`** is required for a public demo. The write-back gate
  below is what keeps that safe.
- **`CAUZON_CORS_ORIGINS`** should be your Pages origin, not `*`, once you know it.

Confirm it:

```bash
curl -s https://cauzon-api-XXXX.us-central1.run.app/api/health
# {"status":"ok","datahub_backend":"mock","write_back_allowed":true,"datahub_ui_url":null}
```

## Stage 2 — a real DataHub

DataHub cannot run on Cloud Run: it needs ~8 GB RAM and holds state across
MySQL, OpenSearch and Kafka. It wants a VM.

```bash
gcloud compute instances create cauzon-datahub \
  --machine-type e2-standard-2 \
  --boot-disk-size 60GB \
  --image-family ubuntu-2404-lts --image-project ubuntu-os-cloud \
  --zone us-central1-a
```

`e2-standard-2` is 2 vCPU / 8 GB, which is what the DataHub quickstart asks for.
It is roughly $35–50/month on demand, so **check current pricing and set a budget
alert before you leave it running.** If GCP cost is the blocker, an equivalent box
elsewhere (e.g. Hetzner CX32, 4 vCPU / 8 GB) is around €7/month; nothing here is
GCP-specific except the `gcloud` commands.

On the VM:

```bash
sudo apt-get update && sudo apt-get install -y python3-pip docker.io docker-compose-v2
sudo usermod -aG docker $USER && newgrp docker
pip3 install --break-system-packages acryl-datahub

datahub docker quickstart              # ~5–10 min on first run
# UI on :9002 (datahub/datahub), GMS API on :8080
```

Then plant the demo lineage graph and mint a token:

```bash
git clone https://github.com/binaydalai/cauzon && cd cauzon
pip3 install --break-system-packages -e ".[datahub]"
python3 scripts/ingest_demo_lineage.py
```

Create a personal access token in the DataHub UI under
**Settings → Access Tokens**, and start the MCP server with mutations enabled
(write-back needs `TOOLS_IS_MUTATION_ENABLED=true`).

### Connecting Cloud Run to GMS

Cloud Run reaching a GCE VM is the fiddly part. Two options:

**Direct VPC egress (recommended).** Keeps GMS on a private IP — it is never
exposed to the internet:

```bash
gcloud run services update cauzon-api \
  --region us-central1 \
  --network default --subnet default \
  --vpc-egress private-ranges-only \
  --set-env-vars "CAUZON_DATAHUB_BACKEND=mcp,DATAHUB_GMS_URL=http://INTERNAL_IP:8080,CAUZON_DATAHUB_UI_URL=https://datahub.YOURDOMAIN" \
  --set-secrets "DATAHUB_TOKEN=datahub-token:latest"
```

**Public IP with a firewall rule.** Simpler, but GMS is then internet-reachable
and protected only by its token. Acceptable for a short-lived demo; put it behind
a reverse proxy with TLS and restrict the source range as tightly as you can. Do
not leave it running afterwards.

Store the token in Secret Manager rather than an env var literal:

```bash
echo -n "YOUR_DATAHUB_TOKEN" | gcloud secrets create datahub-token --data-file=-
gcloud secrets add-iam-policy-binding datahub-token \
  --member "serviceAccount:$(gcloud run services describe cauzon-api --region us-central1 --format='value(spec.template.spec.serviceAccountName)')" \
  --role roles/secretmanager.secretAccessor
```

### Write-back on a real catalog

A real DataHub is shared and durable. A public demo where anyone can press
Investigate would fill it with duplicate dossiers, so **write-back against `mcp`
is off unless you opt in**:

```bash
CAUZON_ALLOW_WRITEBACK=1        # only when you mean it
```

With it off, the live site still does the whole investigation — real reads, real
proof paths from real edges — and simply does not mutate. With it on, the UI shows
a checkbox that defaults to unchecked, so a visitor has to choose.

Setting `CAUZON_DATAHUB_UI_URL` adds **Verify in DataHub →** links from the
finding and from each write-back receipt. That is the most convincing artifact in
the whole submission: a reviewer clicking through from Cauzon into DataHub and
seeing the `root-cause` tag Cauzon applied. Worth the setup on its own.

---

## Running it entirely free

Both stages can be free. The catch is that DataHub wants ~8 GB RAM, and almost no
free tier offers that — with one exception.

### The whole thing on one free VM (Oracle Cloud Always Free)

Oracle's Always Free tier includes an **Ampere A1 (ARM)** allowance of 1,500 OCPU
hours + 9,000 GB hours per month — a steady-state **2 OCPU / 12 GB** instance that
never expires. DataHub's quickstart asks for 2 CPU / 8 GB, so it fits with roughly
4 GB spare, which is enough for the Cauzon API alongside it (~300 MB).

**ARM works — this was verified, not assumed.** Every image in the quickstart
stack publishes `linux/arm64`:

```
acryldata/datahub-gms              amd64, arm64
acryldata/datahub-frontend-react   amd64, arm64
acryldata/datahub-actions          amd64, arm64
acryldata/datahub-upgrade          amd64, arm64
confluentinc/cp-kafka:8.2.2        amd64, arm64
mysql:8.2                          amd64, arm64
opensearchproject/opensearch       amd64, arm64
```

Running both on one box is also *simpler* than splitting them: the API reaches GMS
at `http://localhost:8080`, so there is no VPC connector, no firewall rule, and
GMS is never exposed to the internet.

```bash
# On the instance (Ubuntu 24.04 ARM):
sudo apt-get update && sudo apt-get install -y python3-pip docker.io docker-compose-v2
sudo usermod -aG docker $USER && newgrp docker
pip3 install --break-system-packages acryl-datahub
datahub docker quickstart

git clone https://github.com/binaydalai/cauzon && cd cauzon
python3 scripts/ingest_demo_lineage.py
docker build -t cauzon-api .
docker run -d --restart unless-stopped --network host \
  -e PORT=8000 \
  -e CAUZON_DATAHUB_BACKEND=mcp \
  -e DATAHUB_GMS_URL=http://localhost:8080 \
  -e DATAHUB_TOKEN=... \
  -e CAUZON_DATAHUB_UI_URL=https://YOUR_HOST \
  -e CAUZON_CORS_ORIGINS=https://YOUR_USER.github.io \
  cauzon-api
```

**You need HTTPS**, because a page served over HTTPS from GitHub Pages cannot call
an `http://` API — the browser blocks it as mixed content. Free options: Caddy with
a wildcard-DNS hostname (`caddy reverse-proxy --from <ip>.nip.io --to :8000`
gets a real Let's Encrypt certificate with no domain purchase), a free DuckDNS
subdomain, or a named Cloudflare Tunnel if you already own a domain.

Three risks worth knowing before you commit an afternoon to this:

- **`out of host capacity`** is the common failure. A1 capacity in popular home
  regions is frequently exhausted; you may need to retry across availability
  domains or over a few hours. This is the main reason it might not work today.
- **ARM is a less-travelled path.** Everything checks out, but if something does
  break you will find fewer people who have hit it.
- **Oracle reclaims idle instances** (7-day p95 under 20% CPU *and* network *and*
  memory). DataHub's own footprint keeps memory well above that, so running
  DataHub effectively protects the instance — but do not park an empty VM there
  and expect it to survive.

### Free backend only, on Cloud Run

If you skip DataHub and stay on the demo catalog, Cloud Run's free tier (2M
requests, 180k vCPU-seconds/month) covers this comfortably — as long as you
**drop `--min-instances 1`**, which is what would otherwise push you off free.

That means scale-to-zero and a cold start on the first click. The frontend now
handles that: it shows the recorded replay immediately, then keeps probing with
spacing and **upgrades itself to live once the instance wakes**, with no reload.
Verified against a backend that refuses connections for its first three seconds —
usable at 0.2s, live at 6s.

```bash
gcloud run deploy cauzon-api --source . --region us-central1 \
  --allow-unauthenticated --memory 512Mi --timeout 300 \
  --set-env-vars "CAUZON_CORS_ORIGINS=https://YOUR_USER.github.io"
```

Other always-on free hosts that fit a container this size: **Hugging Face Spaces**
(Docker SDK, sleeps only after ~48 h idle) and **Koyeb** (one free service).
Avoid Render's free tier — it sleeps after 15 minutes and cold-starts in ~50 s,
which is slow enough that a reviewer gives up before the upgrade lands.

### Zero-ops alternative: a DataHub Cloud trial

DataHub offers a hosted free trial (`datahub.com/free-trial/`). For a judging
window measured in days, a trial instance is the least work of all — no VM, no
ARM, no TLS, no capacity lottery, and DataHub keeps it running. Worth checking
whether the trial permits API tokens and mutations before relying on it, since
write-back needs `TOOLS_IS_MUTATION_ENABLED=true`.

Note that DataHub's public demo (`demo.datahub.com`) is **not** an option:
`/api/graphql` returns `401`, so there is no anonymous API access to point at.

### What I would actually do with four days left

Deploy the free Cloud Run backend on the demo catalog and let the header say
`Live agent · demo catalog` — that is honest, free, and cannot break. Then prove
the DataHub half with evidence rather than uptime: run the live write-back locally
once, film the DataHub UI showing the `root-cause` tag, and keep
`examples/live-proof/` as the paper trail. A VM that dies unattended at 3 a.m.
mid-judging is worse than never having claimed it.

---

## Environment reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8080` | Injected by Cloud Run |
| `CAUZON_DATAHUB_BACKEND` | `mock` | `mock` or `mcp` |
| `CAUZON_MOCK_SCENARIO` | `freshness` | Ignored by the API, which serves all three |
| `DATAHUB_GMS_URL` | `http://localhost:8080` | GMS endpoint (`mcp`) |
| `DATAHUB_TOKEN` | — | Personal access token (`mcp`) |
| `CAUZON_ALLOW_WRITEBACK` | off for `mcp` | Permit catalog mutations |
| `CAUZON_DATAHUB_UI_URL` | — | Enables "Verify in DataHub" links |
| `CAUZON_CORS_ORIGINS` | `*` | Set to your frontend origin |
| `CAUZON_LLM_NARRATION` | off | Claude-written dossier narrative |

## Local check before deploying

```bash
docker build -t cauzon-api .
docker run --rm -p 8080:8080 -e PORT=8080 cauzon-api
curl -s localhost:8080/api/health
```

## Teardown

Stage 2 is the part that costs money. Delete it when the judging window closes:

```bash
gcloud compute instances delete cauzon-datahub --zone us-central1-a
gcloud run services update cauzon-api --region us-central1 \
  --set-env-vars CAUZON_DATAHUB_BACKEND=mock
```

Reverting to `mock` keeps the site fully working — the agent still executes live,
the header just says `demo catalog` again instead of `real DataHub`.
