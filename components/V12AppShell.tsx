"use client";
import Link from "next/link";
import {ReactNode} from "react";

const items=[
  ["⌂","Dashboard","/"],
  ["◉","Dev Cloud","/app/dev-cloud"],
  ["▤","Workspaces","/app/workspaces"],
  ["⬡","Sandboxes","/app/sandboxes"],
  ["⇢","Repository Delivery","/app/delivery"],
  ["◇","Releases","/app/releases"],
  ["↗","Deployments","/app/deployments"],
  ["⌁","Secrets & Grants","/app/secrets"],
  ["▣","Artifacts","/app/artifacts"],
  ["◈","Founder Cockpit","/app/founder-cockpit"],
];
export function V12AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
  return <div className="v8Shell"><aside className="v8Side"><Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>Secure AI Dev Cloud · v12</small></span></Link><div className="v8NavLabel">AI DEVELOPMENT CLOUD</div><nav>{items.map(([i,n,h])=><Link key={h} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav><div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Founder control plane</small></div></div></aside><main className="v8Main"><header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header><div className="v8Content">{children}</div></main></div>
}
