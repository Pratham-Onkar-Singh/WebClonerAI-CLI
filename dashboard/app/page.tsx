import { headers } from "next/headers";
import EventBrowser, { AuditEvent } from "./viewer";

export const dynamic = "force-dynamic";

export default async function Page() {
  const incoming = await headers();
  if (!["127.0.0.1:3000", "localhost:3000"].includes(incoming.get("host") ?? "")) {
    return <main><h1>Local access only</h1><p>Open http://127.0.0.1:3000.</p></main>;
  }
  let events: AuditEvent[] = [];
  let error = "";
  try {
    const response = await fetch("http://127.0.0.1:8765/events", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error("API unavailable");
    events = (await response.json()).events;
  } catch {
    error = "The audit API is unavailable. Start it with python3 -m webcloner.api --audit .webcloner/demo-events.jsonl, then refresh.";
  }
  return <main>
    <header><div className="brand">◈ WebCloner <span>EXECUTION AUDIT</span></div><span className="local">Local · Read only</span></header>
    <section className="intro"><p className="eyebrow">CONTROLLED AGENT EXECUTION</p><h1>Every action.<br />An explainable decision.</h1><p>Inspect what the agent requested, why policy allowed or denied it, and what happened next.</p></section>
    {error ? <aside role="alert">{error}</aside> : null}
    <EventBrowser events={events} />
    <footer>Latest 500 events from a bounded log tail. Policy timing excludes model, network, and container execution. Approvals are available only in the trusted CLI.</footer>
  </main>;
}
