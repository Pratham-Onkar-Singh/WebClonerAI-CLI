"use client";

import { useState } from "react";

export type AuditEvent = {
  time: number; event: string; request_id?: string; action?: string; ok?: boolean;
  decision?: { request_id: string; action: string; verdict: string; reason: string; matched_rule: string; policy_version: string; evaluation_ms: number };
  [key: string]: unknown;
};

export default function EventBrowser({ events }: { events: AuditEvent[] }) {
  const [verdict, setVerdict] = useState("");
  const [query, setQuery] = useState("");
  const intents = events.filter(e => e.event === "intent");
  const shown = events.filter(e => (!verdict || e.decision?.verdict === verdict) && JSON.stringify(e).toLowerCase().includes(query.toLowerCase()));
  return <>
    <section className="stats" aria-label="Decisions in this log window">
      {[["Requests", intents.length], ["Allowed", intents.filter(e => e.decision?.verdict === "allow").length], ["Denied", intents.filter(e => e.decision?.verdict === "deny").length], ["Approval required", intents.filter(e => e.decision?.verdict === "require_approval").length]].map(([label, count]) => <div key={label}><span>{label}</span><strong>{count}</strong></div>)}
    </section>
    <section className="feed">
      <div className="toolbar"><h2>Event stream <small>{shown.length}</small></h2><div className="filters">
        <label>Search<input value={query} onChange={e => setQuery(e.target.value)} placeholder="Tool, rule, or request ID" /></label>
        <label>Decision<select value={verdict} onChange={e => setVerdict(e.target.value)}><option value="">All events</option><option value="allow">Allowed</option><option value="deny">Denied</option><option value="require_approval">Approval required</option></select></label>
        <button onClick={() => window.location.reload()}>Refresh</button>
      </div></div>
      {!shown.length ? <div className="empty">No matching events. Run the offline demo or adjust your filters.</div> : shown.map((event, index) => {
        const d = event.decision;
        return <details key={`${event.time}-${index}`}>
          <summary><span className={`badge ${d?.verdict ?? "lifecycle"}`}>{d?.verdict?.replaceAll("_", " ") ?? event.event}</span><span className="event-name">{d?.action ?? event.action ?? event.event}<small>{d?.reason ?? (event.ok === undefined ? event.request_id : event.ok ? "Execution completed" : "Execution failed")}</small></span><span className="timing">{d ? `${d.evaluation_ms.toFixed(3)} ms` : ""}<small>{new Date(event.time * 1000).toISOString().slice(11, 19)} UTC</small></span></summary>
          <pre>{JSON.stringify(event, null, 2)}</pre>
        </details>;
      })}
    </section>
  </>;
}
