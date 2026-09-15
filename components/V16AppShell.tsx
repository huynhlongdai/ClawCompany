"use client";
import Link from "next/link";
import {ReactNode} from "react";
const items=[
 ["⛬","Collaboration Fabric","/app/collaboration"],
 ["◇","Knowledge Mesh","/app/knowledge-mesh"],
 ["♔","Nina SRE Control","/app/sre-control"],
 ["◉","Production Trust","/app/production-trust"],
 ["▣","Engineering OS","/app/engineering"],
 ["◈","Founder Cockpit","/app/founder-cockpit"],
];
export function V16AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
 return <div className="v8Shell"><aside className="v8Side"><Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>Agent Collaboration & Knowledge Mesh · v16</small></span></Link><div className="v8NavLabel">MULTI-COMPANY AGENT OS</div><nav>{items.map(([i,n,h])=><Link key={h} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav><div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Nina · điều phối agent liên công ty</small></div></div></aside><main className="v8Main"><header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header><div className="v8Content">{children}</div></main></div>
}
