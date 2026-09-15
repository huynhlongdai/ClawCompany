"use client";
import Link from "next/link";
import {usePathname, useSearchParams} from "next/navigation";
import {ReactNode, Suspense, useEffect, useState} from "react";
import {Icon, IconName} from "./Icon";
import {LogoLockup} from "./Logo";
import {apiV17} from "../lib/api";

/* Vỏ ứng dụng — dựng theo mockup người dùng gửi.
   Khác bản trước: topbar có ô tìm kiếm ⌘K + nút "Tạo mới" + chuông + đồng hồ,
   và có thể nhận thêm một cột phải (rail) cho "Nhiệm vụ của bạn" / Nina.
   Trang nào không truyền rail thì vẫn là hai cột như cũ. */

type NavItem = {icon: IconName; label: string; href: string; countKey?: string};

const GROUPS: [string, NavItem[]][] = [
  ["Tổ chức", [
    {icon: "home", label: "Trang chủ", href: "/app/os"},
    {icon: "building", label: "Công ty", href: "/app/os?tab=companies", countKey: "companies"},
    {icon: "users", label: "Nhân sự", href: "/app/os?tab=people", countKey: "members"},
    {icon: "sparkle", label: "AI Agents", href: "/app/os?tab=agents", countKey: "agents"},
  ]],
  ["Vận hành", [
    {icon: "board", label: "Dự án", href: "/app/os?tab=projects"},
    {icon: "check", label: "Nhiệm vụ", href: "/app/os?tab=tasks"},
    {icon: "book", label: "Kiến thức", href: "/app/os?tab=knowledge"},
    {icon: "pencil", label: "Vận hành tổ chức", href: "/app/workspace-ops"},
  ]],
  ["Phối hợp agent", [
    {icon: "room", label: "Collaboration Fabric", href: "/app/collaboration"},
    {icon: "mesh", label: "Knowledge Mesh", href: "/app/knowledge-mesh"},
    {icon: "crown", label: "Nina SRE Control", href: "/app/sre-control"},
    {icon: "gear", label: "Lõi OpenClaw", href: "/app/openclaw"},
    {icon: "pulse", label: "Phiên đang chạy", href: "/app/live-runs"},
  ]],
];

/* useSearchParams buộc Next bỏ prerender tĩnh nếu thiếu ranh giới Suspense
   ("useSearchParams() should be wrapped in a suspense boundary" khi build),
   nên phần đọc query param nằm riêng. */
function NavGroups({currentTab}: {currentTab: string}) {
  const pathname = usePathname();
  /* Mockup có số đếm cạnh Nhân sự (128) và AI Agents (86). Lấy số THẬT từ
     /api/v17/workspace/overview thay vì ghim hằng số — một con số sai còn tệ
     hơn không có số. Lỗi thì đơn giản là không hiện. */
  const [counts, setCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    let alive = true;
    apiV17.overview()
      .then((o: any) => { if (alive) setCounts(o?.kpis || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  return <>
    {GROUPS.map(([label, items]) => <div key={label}>
      <div className="v8NavLabel">{label}</div>
      <nav>
        {items.map(item => {
          const [base, query = ""] = item.href.split("?");
          const itemTab = query.startsWith("tab=") ? query.slice(4) : "";
          const active = pathname === base && itemTab === currentTab;
          return <Link key={item.href} href={item.href} className={`v8Nav${active ? " active" : ""}`}>
            <i><Icon name={item.icon}/></i>
            <span>{item.label}</span>
            {item.countKey && counts[item.countKey] !== undefined && <em>{counts[item.countKey]}</em>}
          </Link>;
        })}
      </nav>
    </div>)}
  </>;
}

function NavGroupsWithTab() {
  const params = useSearchParams();
  return <NavGroups currentTab={params.get("tab") || ""}/>;
}

/* Đồng hồ trong mockup là ngày + giờ thật. Render phía client sau khi mount
   để tránh lệch giữa HTML tĩnh và trình duyệt (hydration mismatch). */
function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);
  if (!now) return <div className="clockBox" style={{minWidth: 128}}/>;
  return <div className="clockBox">
    <b>{now.toLocaleDateString("vi-VN", {weekday: "long", day: "numeric", month: "long", year: "numeric"})}</b>
    <span className="clockTime">{now.toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"})}</span>
  </div>;
}

export function V17AppShell({title, subtitle, action, rail, children}: {
  title: string; subtitle: string; action?: ReactNode; rail?: ReactNode; children: ReactNode;
}) {
  return <div className={rail ? "shell3" : "v8Shell"}>
    <aside className="v8Side">
      <Link href="/app/os" className="v8Brand">
        <LogoLockup hole="#161a2b"/>
      </Link>

      <Suspense fallback={<NavGroups currentTab=""/>}>
        <NavGroupsWithTab/>
      </Suspense>

      <div className="v8SideFoot">
        <span className="crown"><Icon name="crown" size={16}/></span>
        <div>
          <b>Nova Holding</b>
          <small>Nina · AI Chief of Staff</small>
        </div>
      </div>
    </aside>

    <main className="v8Main">
      <header className="topBar2">
        <button className="searchWide" title="Tìm kiếm (chưa nối)">
          <Icon name="search" size={16}/>
          <span>Tìm agent, dự án, tài liệu, người…</span>
          <kbd>⌘K</kbd>
        </button>
        {action}
        <button className="bellBtn" title="Thông báo">
          <Icon name="bell" size={17}/>
          <em/>
        </button>
        <Clock/>
      </header>

      <div className="v8Content">
        {/* Trang chủ dùng hero làm tiêu đề (như mockup), nên truyền title=""
            để không có hai tiêu đề chồng nhau. */}
        {!!title && <div className="pageHeader">
          <div style={{minWidth: 0}}>
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </div>
        </div>}
        {children}
      </div>
    </main>

    {rail && <aside className="rail"><div className="railSticky">{rail}</div></aside>}
  </div>;
}
