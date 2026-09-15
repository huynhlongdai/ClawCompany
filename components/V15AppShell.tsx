"use client";
import Link from "next/link";
import {ReactNode} from "react";
const items=[
 ["♔","Nina SRE Control","/app/sre-control"],
 ["◉","Production Trust","/app/production-trust"],
 ["∿","Telemetry Federation","/app/telemetry-federation"],
 ["⌘","Secrets Federation","/app/secrets-federation"],
 ["⌬","Distributed Runners","/app/runners"],
 ["↗","Progressive Delivery","/app/progressive-delivery"],
 ["⚑","Incidents","/app/incidents"],
 ["▣","Engineering OS","/app/engineering"],
 ["◈","Founder Cockpit","/app/founder-cockpit"],
];
export function V15AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
 return <div className="v8Shell"><aside className="v8Side"><Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>Production Trust & Autonomous SRE · v15</small></span></Link><div className="v8NavLabel">PRODUCTION CONTROL PLANE</div><nav>{items.map(([i,n,h])=><Link key={h} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav><div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Nina SRE · governed recovery</small></div></div></aside><main className="v8Main"><header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header><div className="v8Content">{children}</div></main></div>
}
