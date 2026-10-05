"use client";
import Link from "next/link";
import {useMemo, useState} from "react";
import {Icon} from "./Icon";
import {SYSTEM_TOOLS} from "../lib/nav";

/* Danh bạ công cụ — 35 console chuyên sâu không nằm trên sidebar.
   Chúng có thật và chạy được; đưa hết lên sidebar thì sidebar dài 50 dòng và
   không ai tìm thấy gì. Ở đây chúng chia theo khu vực, có ô lọc. */

const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").toLowerCase();

export function SystemDirectory() {
  const [q, setQ] = useState("");
  const areas = useMemo(() => {
    const f = fold(q.trim());
    const tools = SYSTEM_TOOLS.filter(t => !f || fold(`${t.label} ${t.desc} ${t.area}`).includes(f));
    const order: string[] = [];
    for (const t of tools) if (!order.includes(t.area!)) order.push(t.area!);
    return order.map(a => ({area: a, tools: tools.filter(t => t.area === a)}));
  }, [q]);

  return <div className="ui-stack">
    <div className="ui-filter">
      <Icon name="search" size={15}/>
      <input value={q} onChange={e => setQ(e.target.value)} placeholder={`Lọc ${SYSTEM_TOOLS.length} công cụ…`} aria-label="Lọc công cụ"/>
    </div>
    {areas.length === 0 && <p className="ui-empty-line">Không có công cụ nào khớp “{q}”.</p>}
    {areas.map(({area, tools}) => <section key={area} className="ui-section">
      <header className="ui-section-head"><h2>{area}</h2><span className="ui-num">{tools.length}</span></header>
      <div className="ui-tiles">
        {tools.map(t => <Link key={t.href} href={t.href} className="ui-tile">
          <span className="ui-row-icon"><Icon name={t.icon} size={16}/></span>
          <span className="ui-tile-body"><b>{t.label}</b><small>{t.desc}</small></span>
        </Link>)}
      </div>
    </section>)}
  </div>;
}
