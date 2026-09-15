"use client";
import Link from "next/link";
import {ReactNode} from "react";

const items=[
  ["⌂","Dashboard","/"],
  ["◉","Executive Control","/app/control-center"],
  ["◎","Executive Goals","/app/goals"],
  ["N","Nina Planner","/app/nina"],
  ["✦","AI Workforce","/app/agents"],
  ["⌘","Org Memory","/app/memory"],
  ["$","Budgets","/app/budgets"],
  ["↻","Autonomy & Ops","/app/autonomy"],
  ["⇄","Workflow Builder","/app/workflows"],
  ["◇","Company Factory","/app/company-factory"],
  ["◎","Customer Portal","/portal"],
];
export function V9AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
  return <div className="v8Shell"><aside className="v8Side"><Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>AI Company OS · v9</small></span></Link><div className="v8NavLabel">AUTONOMOUS OPERATIONS</div><nav>{items.map(([i,n,h])=><Link key={h} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav><div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Founder command center</small></div></div></aside><main className="v8Main"><header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header><div className="v8Content">{children}</div></main></div>
}
