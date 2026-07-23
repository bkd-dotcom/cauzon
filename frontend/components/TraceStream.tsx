"use client";

type TraceEvent = {
  phase: string;
  message: string;
  data?: any;
};

export default function TraceStream({ trace }: { trace: TraceEvent[] }) {
  return (
    <div className="trace">
      {trace.map((ev, i) => (
        <div key={i} className="trace-item">
          <span className={`phase-tag phase-${ev.phase}`}>{ev.phase}</span>
          <span className="trace-msg">{ev.message}</span>
        </div>
      ))}
    </div>
  );
}
