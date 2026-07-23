"use client";

export default function Diagnosis({ diagnosis }: { diagnosis: any }) {
  const grounded = diagnosis.grounded;
  const cause = diagnosis.root_cause;
  return (
    <div className={`card ${grounded ? "result-grounded" : "result-ungrounded"}`}>
      <h2>{grounded ? "✅ Grounded root cause" : "⚠️ No grounded root cause"}</h2>
      {grounded && cause ? (
        <>
          <div className="kpi">
            <div>
              <span className="label">Root cause</span>
              <span className="value">{cause.name}</span>
            </div>
            <div>
              <span className="label">Confidence</span>
              <span className="value">{Math.round(diagnosis.confidence * 100)}%</span>
            </div>
            <div>
              <span className="label">Hops upstream</span>
              <span className="value">{cause.hops_from_symptom}</span>
            </div>
          </div>
          {cause.evidence_notes?.length > 0 && (
            <>
              <p className="incident-meta" style={{ marginTop: 8 }}>Evidence:</p>
              <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
                {cause.evidence_notes.map((n: string, i: number) => (
                  <li key={i} className="incident-meta">{n}</li>
                ))}
              </ul>
            </>
          )}
          <p style={{ marginTop: 10 }}>
            <strong>Recommended fix:</strong> {diagnosis.recommended_fix}
          </p>
        </>
      ) : (
        <p className="incident-meta">
          Cauzon refused to write an ungrounded diagnosis back to the catalog.
          Escalating to a human.
        </p>
      )}
    </div>
  );
}
