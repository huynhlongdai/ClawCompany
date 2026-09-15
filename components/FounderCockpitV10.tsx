"use client";
import {useEffect,useState} from "react";
import {apiV10} from "../lib/api";

type Any=Record<string,any>;
const n=(v:any)=>Number(v||0).toLocaleString();
export function FounderCockpitV10(){
  const [data,setData]=useState<Any|null>(null);const [error,setError]=useState("");const [loading,setLoading]=useState(true);
  const load=async()=>{setLoading(true);try{setData(await apiV10.founderCockpit() as Any);setError("")}catch(e:any){setError(e.message)}finally{setLoading(false)}};
  useEffect(()=>{load();const t=setInterval(load,15000);return()=>clearInterval(t)},[]);
  const m=data?.metrics||{};
  return <>
    <section className="v10Hero"><div><span className="v10Eyebrow">FOUNDER LIVE CONTROL PLANE</span><h2>Long, công ty đang tự vận hành.</h2><p>Event bus hợp nhất runtime, agent-to-agent message, artifacts, QA, SLA và Nina decision loop thành một luồng quan sát được.</p></div><div className="v10Live"><i/><b>{loading?"…":"LIVE"}</b><small>refresh 15s</small></div></section>
    {error&&<div className="portalError">{error}</div>}
    <div className="v10Metrics">
      {[['Pending events',m.pending_events],['Agent messages',m.messages_24h],['Ready artifacts',m.ready_artifacts],['QA changes',m.qa_changes_requested],['SLA breaches',m.sla_breaches],['Incidents',m.open_recovery_incidents],['Approvals',m.pending_approvals],['Active goals',m.active_goals]].map(([a,b])=><article key={String(a)}><span>{a}</span><b>{n(b)}</b></article>)}
    </div>
    <div className="v10Grid">
      <section className="v8Card"><div className="v8CardHead"><div><b>Company event stream</b><small>Durable events waiting for or already processed by triggers</small></div><button onClick={load} className="v8Ghost">Refresh</button></div><div className="v10Stream">{(data?.events||[]).map((e:Any)=><div className="v10StreamRow" key={e.id}><span className={`v10EventDot ${e.status}`}/><div><b>{e.event_type}</b><small>{e.source} · #{e.id}</small></div><em>{e.status}</em></div>)}{!data?.events?.length&&<p className="v9Empty">No events yet.</p>}</div></section>
      <section className="v8Card"><div className="v8CardHead"><div><b>Nina continuous decision loop</b><small>Latest situational snapshots and decisions</small></div></div>{(data?.decision_runs||[]).map((r:Any)=><div className="v10Decision" key={r.id}><div><b>Loop run #{r.id}</b><small>{r.created_at?new Date(r.created_at).toLocaleString():""}</small></div><div className="v10DecisionChips">{(r.decisions||[]).map((d:Any,i:number)=><span key={i}>{d.type}: {d.reason}</span>)}</div></div>)}{!data?.decision_runs?.length&&<p className="v9Empty">Decision loop has not ticked yet.</p>}</section>
    </div>
    <div className="v10Grid3">
      <section className="v8Card"><div className="v8CardHead"><div><b>Artifacts</b><small>Source, reports and deliverables</small></div></div>{(data?.artifacts||[]).slice(0,7).map((x:Any)=><div className="v10Mini" key={x.id}><div><b>{x.logical_path||x.name}</b><small>{x.artifact_type} · v{x.version}</small></div><span>{x.status}</span></div>)}</section>
      <section className="v8Card"><div className="v8CardHead"><div><b>Agent messages</b><small>Delegation and handoff communication</small></div></div>{(data?.messages||[]).slice(0,7).map((x:Any)=><div className="v10Mini" key={x.id}><div><b>{x.subject||x.message_type}</b><small>{String(x.content||"").slice(0,70)}</small></div><span>{x.priority}</span></div>)}</section>
      <section className="v8Card"><div className="v8CardHead"><div><b>Quality & SLA</b><small>Things requiring founder/manager attention</small></div></div>{(data?.sla_incidents||[]).slice(0,4).map((x:Any)=><div className="v10Mini danger" key={`s${x.id}`}><div><b>SLA #{x.id}</b><small>{x.summary}</small></div><span>{x.status}</span></div>)}{(data?.evaluations||[]).filter((x:Any)=>x.verdict==='changes_requested').slice(0,4).map((x:Any)=><div className="v10Mini warn" key={`q${x.id}`}><div><b>Artifact #{x.artifact_id}</b><small>QA score {x.score}</small></div><span>{x.verdict}</span></div>)}</section>
    </div>
  </>
}
