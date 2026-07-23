"use client";

import { useEffect, useState } from "react";
import TraceStream from "@/components/TraceStream";
import ProofPath from "@/components/ProofPath";
import Diagnosis from "@/components/Diagnosis";

const API = process.env.NEXT_PUBLIC_CAUZON_API || "http://localhost:8000";

type Incident = {
  urn: string;
  title: string;
  description: string;
  failed_assertion?: string;
  detected_at?: string;
};

export default function Home() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [trace, setTrace] = useState<any[]>([]);
  const [diagnosis, setDiagnosis] = useState<any | null>(null);
  const [running, setRunning] = useState(false);
  const [writeBacks, setWriteBacks] = useState<any[]>([]);

  useEffect(() => {
    fetch(`${API}/api/incidents`)
      .then((r) => r.json())
      .then((data) => {
        setIncidents(data);
        if (data.length) setSelected(data[0]);
      })
      .catch(() => setIncidents([]));
  }, []);

  function investigate() {
    if (!selected) return;
    setRunning(true);
    setTrace([]);
    setDiagnosis(null);
    setWriteBacks([]);

    // Prefer WebSocket for live streaming; fall back to POST.
    const wsUrl = API.replace(/^http/, "ws") + "/ws/investigate";
    try {
      const ws = new WebSocket(wsUrl);
      ws.onopen = () => ws.send(JSON.stringify({ ...selected, write_back: true }));
      ws.onmessage = (msg) => {
        const payload = JSON.parse(msg.data);
        if (payload.type === "trace") {
          setTrace((t) => [...t, payload.event]);
        } else if (payload.type === "diagnosis") {
          setDiagnosis(payload.diagnosis);
          setWriteBacks(payload.diagnosis.write_backs || []);
          setRunning(false);
        }
      };
      ws.onerror = () => fallbackPost();
    } catch {
      fallbackPost();
    }
  }

  function fallbackPost() {
    fetch(`${API}/api/investigate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...selected, write_back: true }),
    })
      .then((r) => r.json())
      .then((d) => {
        setTrace(d.trace || []);
        setDiagnosis(d);
        setWriteBacks(d.write_backs || []);
      })
      .finally(() => setRunning(false));
  }

  return (
    <main className="container">
      <div className="header">
        <h1>🔎 Cauzon</h1>
        <span className="badge">path-grounded RCA for DataHub</span>
      </div>
      <p className="subtitle">
        Every root cause, proven from the source. Cauzon walks DataHub lineage
        upstream and only blames a table when it can show the verifiable path.
      </p>

      <div className="card">
        <h2>Open incidents</h2>
        {incidents.length === 0 && (
          <p className="incident-meta">
            No backend reachable. Start it with{" "}
            <code>uvicorn backend.main:app --port 8000</code>.
          </p>
        )}
        {incidents.map((inc) => (
          <div
            key={inc.urn}
            className="card"
            style={{
              cursor: "pointer",
              borderColor: selected?.urn === inc.urn ? "var(--accent)" : undefined,
              background: "var(--panel-2)",
            }}
            onClick={() => setSelected(inc)}
          >
            <div className="incident-title">{inc.title}</div>
            <div className="incident-meta">
              {inc.failed_assertion && <>Assertion: {inc.failed_assertion} · </>}
              {inc.detected_at}
            </div>
          </div>
        ))}
        <button className="btn" disabled={!selected || running} onClick={investigate}>
          {running ? "Investigating…" : "🔍 Investigate"}
        </button>
      </div>

      {trace.length > 0 && (
        <div className="card">
          <h2>Live reasoning trace</h2>
          <TraceStream trace={trace} />
        </div>
      )}

      {diagnosis && <Diagnosis diagnosis={diagnosis} />}

      {diagnosis?.proof_path && (
        <div className="card">
          <h2>Verifiable proof path</h2>
          <ProofPath proof={diagnosis.proof_path} />
        </div>
      )}

      {writeBacks.length > 0 && (
        <div className="card">
          <h2>Written back to DataHub</h2>
          {writeBacks.map((w, i) => (
            <div key={i} className="writeback-item">
              {w.op === "save_document" && `📄 save_document → ${w.title}`}
              {w.op === "add_tags" && `🏷️  add_tags [${(w.tags || []).join(", ")}] → ${short(w.urn)}`}
              {w.op === "update_description" && `📝 update_description → ${short(w.urn)}`}
            </div>
          ))}
          <p className="incident-meta" style={{ marginTop: 10 }}>
            The next person — or agent — inherits this knowledge.
          </p>
        </div>
      )}

      <p className="footer">
        Cauzon · Apache-2.0 · built on the DataHub Agent Context Kit + MCP Server
      </p>
    </main>
  );
}

function short(urn: string) {
  const m = urn.match(/,([^,]+),PROD\)/);
  return m ? m[1] : urn;
}
