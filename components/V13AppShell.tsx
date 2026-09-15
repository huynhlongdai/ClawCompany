"use client";
import Link from "next/link";
import {ReactNode} from "react";

const items=[
  ["⌂","Dashboard","/"],
  ["◈","Engineering OS","/app/engineering"],
  ["⌘","Workspace Gateway","/app/workspace-gateway"],
  ["⌁","CI/CD Graph","/app/cicd"],
  ["⌾","Supply Chain","/app/supply-chain"],
  ["◇","Release Manager","/app/release-manager"],
  ["▤","Dev Cloud","/app/dev-cloud"],
  ["⇢","Repository Delivery","/app/delivery"],
  ["▣","Artifacts","/app/artifacts"],
  ["♔","Founder Cockpit","/app/founder-cockpit"],
];
export function V13AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
  return <div className="v8Shell"><aside className="v8Side"><Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>AI Engineering Organization · v13</small></span></Link><div className="v8NavLabel">ENGINEERING CONTROL PLANE</div><nav>{items.map(([i,n,h])=><Link key={h} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav><div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Nina-governed SDLC</small></div></div></aside><main className="v8Main"><header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header><div className="v8Content">{children}</div></main></div>
}
