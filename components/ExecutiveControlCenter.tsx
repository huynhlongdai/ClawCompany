"use client";
import {useEffect,useState} from "react";
import {AuthGate} from "./AuthGate";
import {V9AppShell} from "./V9AppShell";
import {apiV9} from "../lib/api";

type Control={autonomy:{mode:string;max_auto_risk:string;max_concurrent_runs:number};metrics:Record<string,number>;goals:any[];cycles:any[];incidents:any[];budgets:any[]};
export function ExecutiveControlCenter(){
 const [data,setData]=useState<Control|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 async function load(){setBusy(true);setError("");try{setData(await apiV9.controlCenter() as Control)}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 useEffect(()=>{load()},[]);
 const m=data?.metrics||{};
 return <AuthGate><V9AppShell title="Executive Control Center" subtitle="Founder view of goals, delegation, risk, approvals, memory and budget" action={<button className="v8Ghost" onClick={load} disabled={busy}>{busy?"Refreshing…":"Refresh"}</button>}>
   {error&&<div className="v8Error">{error}</div>}
   <section className="v9Hero"><div><span className="v8Pill">AUTONOMY MODE · {data?.autonomy?.mode||"—"}</span><h2>The company is operating through governed AI delegation.</h2><p>Nina plans and delegates. Managers and agents execute through the runtime. Budgets, risk thresholds and approvals remain explicit controls.</p></div><div className="v9Pulse"><span>LIVE</span><b>{m.running_assignments||0}</b><small>running assignments</small></div></section>
   <div className="v9Metrics">
    <Metric label="Active goals" value={m.active_goals||0}/><Metric label="Running AI work" value={m.running_assignments||0}/><Metric label="Open incidents" value={m.open_incidents||0}/><Metric label="Pending approvals" value={m.pending_approvals||0}/><Metric label="Org memories" value={m.memory_items||0}/><Metric label="AI cost · 24h" value={`$${Number(m.usage_cost_24h||0).toFixed(2)}`}/>
   </div>
   <div className="v9Grid2">
    <section className="v8Card"><div className="v8CardHead"><div><b>Executive goals</b><span>Outcome-oriented company objectives</span></div></div><div className="v9List">{(data?.goals||[]).map(g=><div className="v9Row" key={g.id}><div><span className={`v9Dot ${g.status}`}/><b>{g.title}</b><small>{g.status} · {g.priority} priority</small></div><div className="v9Progress"><i style={{width:`${g.progress||0}%`}}/><span>{g.progress||0}%</span></div></div>)}{!data?.goals?.length&&<Empty text="No executive goals yet"/>}</div></section>
    <section className="v8Card"><div className="v8CardHead"><div><b>Attention queue</b><span>Incidents and governance stops</span></div></div><div className="v9List">{(data?.incidents||[]).map(x=><div className="v9Incident" key={x.id}><span>{x.severity}</span><div><b>{x.incident_type}</b><small>{x.error||"Execution needs attention"}</small></div><em>{x.status}</em></div>)}{!data?.incidents?.length&&<Empty text="No open incidents"/>}</div></section>
   </div>
   <div className="v9Grid2">
    <section className="v8Card"><div className="v8CardHead"><div><b>Operating cycles</b><span>Nina → manager → AI employee execution loops</span></div></div><div className="v9List">{(data?.cycles||[]).map(c=><div className="v9Row" key={c.id}><div><b>Cycle #{c.id}</b><small>Goal #{c.goal_id} · {c.mode}</small></div><em className="v9Status">{c.status}</em></div>)}</div></section>
    <section className="v8Card"><div className="v8CardHead"><div><b>Budget envelopes</b><span>Hard limits before autonomous work</span></div><div className="v9BudgetTotal">${Number(m.budget_spent||0).toFixed(2)} / ${Number(m.budget_limit||0).toFixed(2)}</div></div><div className="v9List">{(data?.budgets||[]).map(b=>{const pct=b.limit?Math.min(100,Math.round(((b.spent+b.reserved)/b.limit)*100)):0;return <div className="v9Budget" key={b.id}><div><b>{b.name}</b><small>{b.currency} · ${Number(b.remaining).toFixed(2)} remaining</small></div><div className="v9Bar"><i style={{width:`${pct}%`}}/></div></div>})}</div></section>
   </div>
 </V9AppShell></AuthGate>
}
function Metric({label,value}:{label:string;value:any}){return <div className="v9Metric"><span>{label}</span><b>{value}</b></div>}
function Empty({text}:{text:string}){return <div className="v9Empty">{text}</div>}
