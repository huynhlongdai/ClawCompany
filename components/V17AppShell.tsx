"use client";
import Link from "next/link";
import {usePathname, useSearchParams} from "next/navigation";
import {ReactNode, Suspense, useEffect, useState} from "react";
import {Icon, IconName} from "./Icon";
import {LogoLockup} from "./Logo";
import {api, apiV17} from "../lib/api";
import {logout} from "../lib/auth";

/* Vỏ ứng dụng — dựng theo mockup người dùng gửi.

   Sidebar là danh sách phẳng đúng như mẫu (Trang chủ → Cài đặt), có số đếm
   thật, rồi tới khối người dùng và ba icon chân trang.

   Một chỗ cố tình khác mẫu: mẫu không có nhóm "Hệ thống", nhưng dự án này có
   40 console hạ tầng thật (OpenClaw, live runs, SRE, trust, telemetry...).
   Bỏ chúng khỏi nav để giống mẫu 100% thì đúng ảnh nhưng mất đường vào những
   trang đang chạy được. Nên chúng nằm trong một nhóm thu gọn ở dưới. */

type NavItem = {icon: IconName; label: string; href: string; countKey?: string};

/* Danh sách chính — đúng thứ tự trong mẫu. */
const MAIN: NavItem[] = [
  {icon: "home", label: "Trang chủ", href: "/app/os"},
  {icon: "building", label: "Công ty", href: "/app/os?tab=companies", countKey: "companies"},
  {icon: "sparkle", label: "AI Agents", href: "/app/os?tab=agents", countKey: "agents"},
  {icon: "users", label: "Nhân sự", href: "/app/os?tab=people", countKey: "members"},
  {icon: "board", label: "Dự án", href: "/app/os?tab=projects"},
  {icon: "check", label: "Nhiệm vụ", href: "/app/os?tab=tasks"},
  {icon: "book", label: "Kiến thức", href: "/app/os?tab=knowledge"},
  {icon: "users", label: "Khách hàng", href: "/app/customers"},
  {icon: "chart", label: "Báo cáo", href: "/app/reports"},
  {icon: "gear", label: "Tự động hoá", href: "/app/workflows"},
  {icon: "doc", label: "Marketplace", href: "/app/marketplace"},
  {icon: "pencil", label: "Vận hành tổ chức", href: "/app/workspace-ops"},
];

/* Các console hạ tầng: có thật, đang chạy, nhưng không có trong mẫu. */
const SYSTEM: NavItem[] = [
  {icon: "room", label: "Collaboration Fabric", href: "/app/collaboration"},
  {icon: "mesh", label: "Knowledge Mesh", href: "/app/knowledge-mesh"},
  {icon: "crown", label: "Nina SRE Control", href: "/app/sre-control"},
  {icon: "gear", label: "Lõi OpenClaw", href: "/app/openclaw"},
  {icon: "pulse", label: "Phiên đang chạy", href: "/app/live-runs"},
];

function NavList({items, currentTab, counts}: {
  items: NavItem[]; currentTab: string; counts: Record<string, number>;
}) {
  const pathname = usePathname();
  return <nav>
    {items.map(item => {
      const [base, query = ""] = item.href.split("?");
      const itemTab = query.startsWith("tab=") ? query.slice(4) : "";
      const active = pathname === base && (base !== "/app/os" || itemTab === currentTab);
      return <Link key={item.href} href={item.href} className={`v8Nav${active ? " active" : ""}`}>
        <i><Icon name={item.icon}/></i>
        <span>{item.label}</span>
        {item.countKey && counts[item.countKey] !== undefined && <em>{counts[item.countKey]}</em>}
      </Link>;
    })}
  </nav>;
}

function SideNav({currentTab}: {currentTab: string}) {
  /* Số đếm trong mẫu (128, 86) lấy số THẬT từ overview. Một con số ghim cứng
     sai còn tệ hơn không có số; lỗi thì đơn giản là không hiện. */
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [openSystem, setOpenSystem] = useState(false);
  useEffect(() => {
    let alive = true;
    apiV17.overview()
      .then((o: any) => { if (alive) setCounts(o?.kpis || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  return <>
    <NavList items={MAIN} currentTab={currentTab} counts={counts}/>
    <div>
      <button className="v8Nav" onClick={() => setOpenSystem(v => !v)}
              style={{justifyContent: "space-between"}}>
        <span style={{display: "flex", alignItems: "center", gap: 10}}>
          <i><Icon name="shield"/></i>
          <span>Hệ thống</span>
        </span>
        <span style={{opacity: .6, fontSize: 11}}>{openSystem ? "−" : "+"}</span>
      </button>
      {openSystem && <NavList items={SYSTEM} currentTab={currentTab} counts={counts}/>}
    </div>
  </>;
}

function SideNavWithTab() {
  const params = useSearchParams();
  return <SideNav currentTab={params.get("tab") || ""}/>;
}

/* Ngày + giờ thật, render phía client sau mount để không lệch hydration. */
function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);
  if (!now) return <div className="clockBox" style={{minWidth: 150}}/>;
  return <div className="clockBox">
    <b>{now.toLocaleDateString("vi-VN", {weekday: "long", day: "numeric", month: "long", year: "numeric"})}</b>
    <span className="clockTime">{now.toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"})}</span>
  </div>;
}

/* Khối người dùng ở chân sidebar, như mẫu: avatar, tên, vai trò, nút thoát. */
function UserBlock() {
  const [me, setMe] = useState<{display_name?: string; email?: string} | null>(null);
  useEffect(() => {
    let alive = true;
    api.me().then((u: any) => { if (alive) setMe(u); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const name = me?.display_name || me?.email?.split("@")[0] || "—";
  return <div className="userBlock">
    <span className="avatarSm">{name.slice(0, 1).toUpperCase()}</span>
    <div style={{minWidth: 0, flex: 1}}>
      <b>{name}</b>
      <small>Founder &amp; CEO</small>
    </div>
    <button className="userMore" title="Đăng xuất"
            onClick={() => { logout(); location.reload(); }}>⋯</button>
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

      <Suspense fallback={<SideNav currentTab=""/>}>
        <SideNavWithTab/>
      </Suspense>

      <div style={{marginTop: "auto", display: "grid", gap: 8}}>
        <UserBlock/>
        <div className="sideIcons">
          <button title="Tìm kiếm"><Icon name="search" size={16}/></button>
          <button title="Thông báo"><Icon name="bell" size={16}/></button>
          <Link href="/app/workspace-ops" title="Cài đặt"><Icon name="gear" size={16}/></Link>
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
