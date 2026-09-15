"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {apiV13} from "../lib/api";
type Any=Record<string,any>;
export function EngineeringOrgConsole(){
 const [data,setData]=useState<Any|null>(null),[error,setError]=useState("");
 useEffect(()=>{apiV13.dashboard().then(x=>setData(x as Any)).catch((e:any)=>setError(e.message))},[]);
 const m=data?.metrics||{};
 const flow=["Idea / Goal","Nina Initiative","Workspace Gateway","CI/CD Graph","Security + SBOM","Release Manager","Progressive Deploy"];
 return <>
  <section className="v13Hero"><div><span>AI ENGINEERING ORGANIZATION</span><h2>Nina điều phối toàn bộ SDLC — agent nào cũng dùng chung một control plane.</h2><p>Provider-specific chat sessions are converted into governed workspace sessions, immutable evidence, CI/CD graph runs, security gates and release decisions. Coding agents never need repository or production credentials.</p><div className="v13Flow">{flow.map((x,i)=><span key={x}><b>{x}</b>{i<flow.length-1&&<i>→</i>}</span>)}</div></div><aside><strong>FOUNDER GUARANTEES</strong><ul><li>Identity-bound workspace access</li><li>Immutable commit provenance</li><li>Deterministic security gate</li><li>Governed release promotion</li><li>Health-aware rollback path</li></ul></aside></section>
  {error&&<div className="portalError">{error}</div>}
  <div className="v13Metrics">{[["Gateway sessions",m.gateway_sessions,"⌘"],["Pipeline graphs",m.pipeline_graphs,"⌁"],["CI running",m.ci_running,"▶"],["Build evidence",m.builds,"▣"],["Security blocked",m.security_blocked,"⚑"],["Release holds",m.release_holds,"◇"],["Active initiatives",m.initiatives_active,"◈"]].map(([l,v,i])=><article key={String(l)}><span>{i}</span><div><small>{l}</small><b>{v??"—"}</b></div></article>)}</div>
  <div className="v13Split"><section className="v8Card"><div className="v8CardHead"><div><b>Nina engineering initiatives</b><small>Goal → governed release path</small></div><Link href="/app/cicd">Open CI/CD →</Link></div><div className="v13RunList">{(data?.initiatives||[]).map((x:Any)=><article key={x.id}><div><span className={`v13Dot ${x.status}`}/><div><b>{x.title}</b><small>repo #{x.repository_id} · pipeline #{x.pipeline_graph_id}</small></div></div><em>{x.status}</em></article>)}{!data?.initiatives?.length&&<div className="v8Empty">No engineering initiative yet</div>}</div></section>
  <section className="v8Card"><div className="v8CardHead"><div><b>Release cognition</b><small>Latest CI, security and deployment state</small></div></div><div className="v13Rail">{(data?.ci_runs||[]).slice(0,4).map((x:Any)=><div key={x.id}><span>CI #{x.id}</span><b>{x.commit_sha?.slice(0,10)||"pending"}</b><em>{x.status}</em></div>)}{(data?.security_reviews||[]).slice(0,3).map((x:Any)=><div key={`s-${x.id}`}><span>Security #{x.id}</span><b>{Math.round(x.score||0)}/100</b><em>{x.verdict}</em></div>)}</div></section></div>
  <section className="v8Card"><div className="v8CardHead"><div><b>Autonomous engineering loop</b><small>Nina does not bypass governance; it advances only when the next gate is satisfied.</small></div></div><div className="v13Loop"><div><span>1</span><b>Plan</b><small>objective + repo + pipeline</small></div><i>→</i><div><span>2</span><b>Execute</b><small>workspace + sandbox + CI</small></div><i>→</i><div><span>3</span><b>Verify</b><small>SBOM + provenance + security</small></div><i>→</i><div><span>4</span><b>Decide</b><small>release manager gate</small></div><i>→</i><div><span>5</span><b>Deploy</b><small>health + rollback</small></div></div></section>
 </>
}
