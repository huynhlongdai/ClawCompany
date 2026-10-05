"use client";
import Link from "next/link";
import {usePathname, useSearchParams} from "next/navigation";
import {ReactNode, Suspense, useEffect, useState} from "react";
import {Icon} from "./Icon";
import {Logo} from "./Logo";
import {CommandPalette} from "./CommandPalette";
import {api} from "../lib/api";
import {logout} from "../lib/auth";
import {NAV, NAV_GROUPS, NavEntry, SYSTEM_PINNED, groupLabel, matchNav} from "../lib/nav";
import {Counts, getCounts, getOrgName, peekCounts, subscribeCounts} from "../lib/counts";

/* Vỏ ứng dụng v6 — một vỏ duy nhất cho mọi route /app/*.

   Trước v6 có mười vỏ (V8…V17AppShell), mỗi vỏ một menu riêng. Giờ chúng đều
   re-export vỏ này, nên 49 route có cùng sidebar, cùng tiêu đề tiếng Việt lấy
   từ lib/nav.ts, cùng tìm kiếm ⌘K và cùng chuông dẫn về Hộp việc.

   Class dùng tiền tố `ui-` để không dính vào hàng trăm quy tắc cũ trong
   globals.css (nhiều cái có !important). Style ở app/v6.css. */

function useCounts() {
  /* Luôn khởi tạo rỗng để HTML server và lần render đầu của client khớp
     nhau; số từ cache được nạp ngay trong effect nên không thấy nháy. */
  const [counts, setCounts] = useState<Counts>({});
  useEffect(() => {
    let alive = true;
    const cached = peekCounts(); if (cached) setCounts(cached);
    getCounts().then(c => { if (alive) setCounts(c); }).catch(() => {});
    const off = subscribeCounts(c => { if (alive) setCounts(c); });
    return () => { alive = false; off(); };
  }, []);
  return counts;
}

function isActive(entry: NavEntry, current?: NavEntry) {
  return !!current && current.href === entry.href;
}

function NavLink({entry, current, counts, onNavigate}: {
  entry: NavEntry; current?: NavEntry; counts: Counts; onNavigate: () => void;
}) {
  const active = isActive(entry, current);
  const n = entry.countKey ? counts[entry.countKey] : undefined;
  return <Link href={entry.href} className={"ui-nav" + (active ? " is-active" : "")}
               aria-current={active ? "page" : undefined} onClick={onNavigate}>
    <Icon name={entry.icon} size={17}/>
    <span className="ui-nav-label">{entry.label}</span>
    {n !== undefined && n > 0 && <em className={"ui-count" + (entry.countKey === "inbox" ? " is-hot" : "")}>{n}</em>}
  </Link>;
}

function SideNav({onNavigate}: {onNavigate: () => void}) {
  const pathname = usePathname();
  const tab = useSearchParams().get("tab") || "";
  const current = matchNav(pathname, tab);
  const counts = useCounts();
  const inSystem = current?.group === "system";
  const [openSystem, setOpenSystem] = useState(inSystem);
  useEffect(() => { if (inSystem) setOpenSystem(true); }, [inSystem]);

  const systemItems = NAV.filter(n => n.group === "system" && (
    n.href === "/app/system" || SYSTEM_PINNED.includes(n.href) || n.href === current?.href));

  return <nav className="ui-nav-wrap" aria-label="Điều hướng chính">
    {NAV_GROUPS.filter(g => g.key !== "system").map(g =>
      <div className="ui-nav-group" key={g.key}>
        {g.label && <p className="ui-nav-heading">{g.label}</p>}
        {NAV.filter(n => n.group === g.key).map(n =>
          <NavLink key={n.href} entry={n} current={current} counts={counts} onNavigate={onNavigate}/>)}
      </div>)}
    <div className="ui-nav-group">
      <button className="ui-nav-heading ui-nav-toggle" aria-expanded={openSystem}
              onClick={() => setOpenSystem(v => !v)}>
        <span>Hệ thống</span>
        <Icon name={openSystem ? "chevron-down" : "chevron-right"} size={14}/>
      </button>
      {openSystem && systemItems.map(n =>
        <NavLink key={n.href} entry={n} current={current} counts={counts} onNavigate={onNavigate}/>)}
    </div>
  </nav>;
}

/* Trang chi tiết (/app/tasks/7, /app/agents/2) khớp với mục cha trong sổ
   đăng ký nhưng không phải chính mục đó: khi ấy dùng tiêu đề trang truyền vào
   và hiện mục cha như một bậc breadcrumb bấm được. */
function useRoute(title: string) {
  const pathname = usePathname();
  const tab = useSearchParams().get("tab") || "";
  const current = matchNav(pathname, tab);
  const detail = !!current && pathname !== current.href.split("?")[0];
  return {current, detail};
}

function Crumbs({title}: {title: string}) {
  const {current, detail} = useRoute(title);
  const group = current ? groupLabel(current.group) : "";
  return <nav className="ui-crumbs" aria-label="Vị trí">
    {group && <><span>{group}</span><Icon name="chevron-right" size={12}/></>}
    {detail && current ? <>
      <Link href={current.href}>{current.label}</Link><Icon name="chevron-right" size={12}/><b>{title}</b>
    </> : <b>{current?.label || title || "ClawCompany"}</b>}
  </nav>;
}

function PageHead({title, subtitle}: {title: string; subtitle: string}) {
  const {current, detail} = useRoute(title);
  /* Một tên cho mỗi khái niệm: nếu route có trong sổ đăng ký thì dùng tên và
     mô tả ở đó, kể cả khi console cũ truyền tiêu đề tiếng Anh. */
  const h = !detail && current ? current.label : title;
  const p = !detail && current ? current.desc : subtitle;
  return <div className="ui-pagehead">
    <h1>{h}</h1>
    {p && <p>{p}</p>}
  </div>;
}

function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  if (!now) return <span className="ui-clock" aria-hidden="true"/>;
  return <time className="ui-clock" dateTime={now.toISOString()}>
    {now.toLocaleDateString("vi-VN", {weekday: "short", day: "numeric", month: "numeric"})}
    <b>{now.toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"})}</b>
  </time>;
}

function Account() {
  const [me, setMe] = useState<any>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    api.me().then(u => { if (alive) setMe(u); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) { if (e.key === "Escape") setOpen(false); return; }
      if (!(e.target as HTMLElement).closest(".ui-acct")) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  const name = me?.display_name || me?.name || me?.email?.split("@")[0] || "Tài khoản";
  return <div className="ui-acct">
    <button className="ui-iconbtn ui-avatar-btn" onClick={() => setOpen(v => !v)} aria-expanded={open}
            aria-haspopup="menu" aria-label="Tài khoản">
      <span className="ui-avatar">{name.slice(0, 1).toUpperCase()}</span>
    </button>
    {open && <div className="ui-pop" role="menu">
      <div className="ui-pop-head"><b>{name}</b><small>{me?.email || ""}</small></div>
      <Link role="menuitem" href="/app/workspace-ops" onClick={() => setOpen(false)}><Icon name="gear" size={15}/>Cài đặt tổ chức</Link>
      <Link role="menuitem" href="/app/system" onClick={() => setOpen(false)}><Icon name="grid" size={15}/>Danh bạ công cụ</Link>
      <button role="menuitem" className="is-danger" onClick={() => { logout(); location.reload(); }}>
        <Icon name="logout" size={15}/>Đăng xuất
      </button>
    </div>}
  </div>;
}

function OrgName() {
  useCounts(); // render lại khi overview về
  return <>{getOrgName() || "AI Organization OS"}</>;
}

function Bell() {
  const counts = useCounts();
  const n = counts.inbox || 0;
  return <Link href="/app/inbox" className="ui-iconbtn" aria-label={n ? `Hộp việc, ${n} mục cần xử lý` : "Hộp việc"}>
    <Icon name="bell" size={17}/>
    {n > 0 && <em className="ui-dot">{n > 9 ? "9+" : n}</em>}
  </Link>;
}

export function AppShell({title, subtitle, action, rail, children}: {
  title: string; subtitle: string; action?: ReactNode; rail?: ReactNode; children: ReactNode;
}) {
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const pathname = usePathname();
  useEffect(() => { setDrawer(false); }, [pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(v => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const close = () => setDrawer(false);

  return <div className={"ui-shell" + (rail ? " has-rail" : "") + (drawer ? " drawer-open" : "")}>
    <a href="#ui-main" className="ui-skip">Bỏ qua tới nội dung</a>
    <aside className="ui-side">
      <Link href="/app/os" className="ui-brand" onClick={close}>
        <Logo size={28} hole="#f6f5f3"/>
        <span><b>ClawCompany</b><small><OrgName/></small></span>
      </Link>
      <Suspense fallback={null}><SideNav onNavigate={close}/></Suspense>
    </aside>
    {drawer && <button className="ui-scrim" aria-label="Đóng menu" onClick={close}/>}

    <div className="ui-main">
      <header className="ui-top">
        <button className="ui-iconbtn ui-menu-btn" aria-label="Mở menu" onClick={() => setDrawer(true)}>
          <Icon name="menu" size={18}/>
        </button>
        <Suspense fallback={<div className="ui-crumbs"/>}><Crumbs title={title}/></Suspense>
        <button className="ui-search" onClick={() => setPalette(true)} aria-label="Tìm kiếm (Ctrl K)">
          <Icon name="search" size={15}/>
          <span>Tìm trang, nhiệm vụ, agent…</span>
          <kbd>⌘K</kbd>
        </button>
        <div className="ui-top-actions">
          {action}
          <Bell/>
          <Clock/>
          <Account/>
        </div>
      </header>

      <main id="ui-main" className="ui-content">
        {!!title && <Suspense fallback={null}><PageHead title={title} subtitle={subtitle}/></Suspense>}
        {children}
      </main>
    </div>

    {rail && <aside className="ui-rail" aria-label="Thông tin bên">{rail}</aside>}
    {palette && <CommandPalette onClose={() => setPalette(false)}/>}
  </div>;
}
