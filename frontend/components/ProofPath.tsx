"use client";

type Proof = {
  symptom_urn: string;
  cause_urn: string;
  nodes: string[];
  edges: { from: string; to: string; via_query?: string | null }[];
  transform_sql?: string | null;
  verified: boolean;
};

function nodeName(urn: string) {
  const m = urn.match(/,([^,]+),PROD\)/);
  return m ? m[1] : urn;
}

export default function ProofPath({ proof }: { proof: Proof }) {
  return (
    <div>
      <div className="proof-path">
        {proof.nodes.map((urn, i) => {
          const isCause = urn === proof.cause_urn;
          const isSymptom = urn === proof.symptom_urn;
          const cls = isCause ? "node cause" : isSymptom ? "node symptom" : "node";
          return (
            <span key={urn} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span className={cls} title={urn}>
                {nodeName(urn)}
                {isCause && " ⛳"}
                {isSymptom && " 🚨"}
              </span>
              {i < proof.nodes.length - 1 && <span className="arrow">→</span>}
            </span>
          );
        })}
      </div>
      <p className="incident-meta">
        {proof.verified
          ? "✅ Path reconstructed from real lineage edges — diagnosis is grounded."
          : "⚠️ Path could not be verified."}
      </p>
      {proof.transform_sql && (
        <>
          <p className="incident-meta">Transform that carried the fault downstream:</p>
          <pre className="sql">{proof.transform_sql}</pre>
        </>
      )}
    </div>
  );
}
