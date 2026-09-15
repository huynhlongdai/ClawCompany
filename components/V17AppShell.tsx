"use client";
import Link from "next/link";
import {ReactNode} from "react";

const groups: [string, [string,string,string][]][] = [
  ["TỔ CHỨC", [
    ["⌂","Trang chủ","/app/os"],
    ["▤","Công ty","/app/os?tab=companies"],
    ["◫","Nhân sự","/app/os?tab=people"],
    ["✦","AI Agents","/app/os?tab=agents"],
  ]],
  ["VẬN HÀNH", [
    ["▣","Dự án","/app/os?tab=projects"],
    ["☑","Nhiệm vụ","/app/os?tab=tasks"],
    ["◇","Kiến thức","/app/os?tab=knowledge"],
    ["✎","Vận hành tổ chức","/app/workspace-ops"],
  ]],
  ["PHỐI HỢP AGENT", [
    ["⛬","Collaboration Fabric","/app/collaboration"],
    ["◈","Knowledge Mesh","/app/knowledge-mesh"],
    ["♔","Nina SRE Control","/app/sre-control"],
    ["⚙","Lõi OpenClaw","/app/openclaw"],
    ["◉","Phiên đang chạy","/app/live-runs"],
  ]],
];

export function V17AppShell({title,subtitle,action,children}:{title:string;subtitle:string;action?:ReactNode;children:ReactNode}){
  return <div className="v8Shell">
    <aside className="v8Side">
      <Link href="/" className="v8Brand"><span className="brandMark"/><span><b>ClawCompany</b><small>AI Organization OS · v35</small></span></Link>
      {groups.map(([label,items])=><div key={label}>
        <div className="v8NavLabel">{label}</div>
        <nav>{items.map(([i,n,h])=><Link key={h+n} href={h} className="v8Nav"><i>{i}</i><span>{n}</span></Link>)}</nav>
      </div>)}
      <div className="v8SideFoot"><span className="crown">♔</span><div><b>Nova Holding</b><small>Nina · AI Chief of Staff</small></div></div>
    </aside>
    <main className="v8Main">
      <header className="v8Top"><div><h1>{title}</h1><p>{subtitle}</p></div>
        <div className="v8TopActions">{action}<Link href="/" className="v8Ghost">← Dashboard</Link></div></header>
      <div className="v8Content">{children}</div>
    </main>
  </div>;
}
