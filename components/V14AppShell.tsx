"use client";
import Link from "next/link";
import {ReactNode} from "react";
const items=[
 ["◈","Engineering OS","/app/engineering"],["⌬","Distributed Runners","/app/runners"],["⌘","Workspace Gateway","/app/workspace-gateway"],
 ["⌁","CI/CD Graph","/app/cicd"],["◉","Trust & Supply Chain","/app/trust"],["↗","Progressive Delivery","/app/progressive-delivery"],
 ["∿","SLO & Telemetry","/app/observability"],["⚑","Incidents","/app/incidents"],["♔","Nina Portfolio","/app/portfolio"],
 ["▣","Founder Cockpit","/app/founder-cockpit"],
];
export function V14AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
 return <div className="v8Shell"><aside className="v8Side"><Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>Distributed Engineering OS · v14</small></span></Link><div className="v8NavLabel">SECURE EXECUTION CONTROL PLANE</div><nav>{items.map(([i,n,h])=><Link key={h} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav><div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Nina governed · SLO protected</small></div></div></aside><main className="v8Main"><header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header><div className="v8Content">{children}</div></main></div>
}
