"use client";
import Link from "next/link";
import {Icon} from "./Icon";
import {LAB_PAGES, MORE_PAGES, NavPage} from "../lib/nav";
import {useLab} from "../lib/prefs";
import {Notice} from "./ui/EmptyState";

/* Danh bạ mọi trang ngoài 8 mục menu. Trang Phòng thí nghiệm chỉ hiện khi bật cờ. */
function Group({title, pages}: {title: string; pages: NavPage[]}) {
  return <section className="ui-section">
    <div className="ui-section-head"><h2>{title}</h2><span className="ui-num" style={{color: "var(--text-muted)"}}>{pages.length}</span></div>
    <div className="ui-panel"><div className="ui-list">
      {pages.map(p => <Link key={p.href} href={p.href} className="ui-row">
        <Icon name={p.icon} size={16}/>
        <span className="ui-row-main"><span className="ui-row-title">{p.label}</span><span className="ui-row-meta">{p.desc}</span></span>
        <span className="ui-row-end"><Icon name="chevron-right" size={14}/></span>
      </Link>)}
    </div></div>
  </section>;
}

export function SystemDirectory() {
  const [lab] = useLab();
  const areas = (list: NavPage[]) => Array.from(new Set(list.map(p => p.area))).map(a => ({a, pages: list.filter(p => p.area === a)}));
  return <div className="ui-grid" style={{gap: 24}}>
    {areas(MORE_PAGES.filter(p => p.href !== "/app/system")).map(g => <Group key={g.a} title={g.a} pages={g.pages}/>)}
    {lab ? areas(LAB_PAGES).map(g => <Group key={g.a} title={`Phòng thí nghiệm · ${g.a}`} pages={g.pages}/>)
      : <Notice>{LAB_PAGES.length} trang ít dùng đang ẩn. Bật ở <Link href="/app/settings/lab">Cài đặt › Phòng thí nghiệm</Link> nếu anh cần.</Notice>}
  </div>;
}
