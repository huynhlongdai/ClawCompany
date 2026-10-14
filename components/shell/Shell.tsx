"use client";
import Link from "next/link";
import dynamic from "next/dynamic";
import {usePathname, useRouter} from "next/navigation";
import {ReactNode, Suspense, useEffect, useState} from "react";
import {Icon} from "../Icon";
import {Logo} from "../Logo";
import {ToastProvider} from "../ui/Toast";
import {SkeletonRows} from "../ui/Skeleton";
import {api} from "../../lib/api";
import {logout} from "../../lib/auth";
import {SECTIONS, sectionFor} from "../../lib/nav";
import {Counts, getCounts, getOrg, peekCounts, subscribeCounts} from "../../lib/counts";
import {ThemePref, useCompanyId, useThemePref} from "../../lib/prefs";

/* Khung ứng dụng UI v2 — MỘT shell, nằm trong app/app/layout.tsx nên mount một
   lần cho mọi route /app/* (trước v2: mỗi trang tự bọc vỏ, 11 bản V*AppShell,
   chuyển trang là dựng lại sidebar + bắn lại request đếm).

   Gồm: bộ đổi công ty · ô ⌘K · đúng 8 mục menu (lib/nav.ts) · tài khoản + giao
   diện sáng/tối · topbar có breadcrumb + chuông · thanh dưới 5 nút ở ≤900px. */

const CommandPalette = dynamic(() => import("./CommandPalette").then(m => m.CommandPalette), {ssr: false});

export function useCounts() {
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

function CompanySwitcher({onNavigate}: {onNavigate: () => void}) {
  useCounts();
  const org = getOrg();
  const [companyId, setCompanyId] = useCompanyId();
  const [open, setOpen] = useState(false);
  const current = org.companies.find(c => c.id === companyId) || org.companies[0];
  useDismiss(open, () => setOpen(false), ".ui-switch");
  return <div className="ui-switch">
    <button className="ui-switch-btn" onClick={() => setOpen(v => !v)} aria-expanded={open} aria-haspopup="menu" data-testid="company-switcher">
      <Logo size={30} hole="var(--bg)"/>
      <span><b translate="no">{current?.name || org.name || "ClawCompany"}</b><small>{org.name ? `${org.name} · ${org.companies.length} công ty` : "Đang tải…"}</small></span>
      <Icon name="chevron-down" size={14}/>
    </button>
    {open && <div className="ui-pop" role="menu">
      <p className="ui-pop-head">Đổi công ty đang xem</p>
      {org.companies.map(c => <button key={c.id} role="menuitemradio" aria-checked={c.id === current?.id} className={c.id === current?.id ? "is-on" : ""}
        onClick={() => { setCompanyId(c.id); setOpen(false); }}><Icon name="building" size={15}/><span className="ui-ellipsis">{c.name}</span></button>)}
      {!org.companies.length && <p className="ui-pop-head">Chưa có công ty nào.</p>}
      <hr/>
      <Link role="menuitem" href="/onboarding" onClick={() => { setOpen(false); onNavigate(); }}><Icon name="plus" size={15}/>Tạo công ty mới</Link>
    </div>}
  </div>;
}

function useDismiss(open: boolean, close: () => void, selector: string) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(selector)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown); document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close, selector]);
}

function SideNav({onNavigate}: {onNavigate: () => void}) {
  const pathname = usePathname();
  const current = sectionFor(pathname);
  const counts = useCounts();
  return <nav className="ui-nav-wrap" aria-label="Điều hướng chính">
    {SECTIONS.map(s => {
      const active = current?.key === s.key;
      const n = s.countKey ? counts[s.countKey] : 0;
      return <Link key={s.key} href={s.href} className={"ui-nav" + (active ? " is-active" : "")} aria-current={active ? "page" : undefined}
                   onClick={onNavigate} data-testid={`nav-${s.key}`}>
        <Icon name={s.icon} size={17}/><span className="ui-nav-label">{s.label}</span>
        {n ? <em className={"ui-count" + (s.key === "inbox" ? " is-hot" : "")}>{n > 99 ? "99+" : n}</em> : null}
      </Link>;
    })}
  </nav>;
}

const THEMES: [ThemePref, string][] = [["light", "Sáng"], ["dark", "Tối"], ["system", "Theo máy"]];

function Account() {
  const [me, setMe] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useThemePref();
  useEffect(() => { let alive = true; api.me().then(u => { if (alive) setMe(u); }).catch(() => {}); return () => { alive = false; }; }, []);
  useDismiss(open, () => setOpen(false), ".ui-acct");
  const name = me?.full_name || me?.display_name || me?.email?.split("@")[0] || "Tài khoản";
  return <div className="ui-acct">
    <button className="ui-acct-btn" onClick={() => setOpen(v => !v)} aria-expanded={open} aria-haspopup="menu" data-testid="account-btn">
      <span className="ui-ava is-human">{name.slice(0, 1).toUpperCase()}</span>
      <span><b>{name}</b><small>{me?.email || ""}</small></span>
      <Icon name="more" size={16} strokeWidth={2.4}/>
    </button>
    {open && <div className="ui-pop" role="menu">
      <p className="ui-pop-head">Giao diện</p>
      <div className="ui-seg" role="radiogroup" aria-label="Giao diện" style={{margin: "0 4px 6px"}}>
        {THEMES.map(([k, l]) => <button key={k} role="radio" aria-checked={theme === k} onClick={() => setTheme(k)} data-testid={`theme-${k}`}>{l}</button>)}
      </div>
      <hr/>
      <Link role="menuitem" href="/app/settings" onClick={() => setOpen(false)}><Icon name="gear" size={15}/>Cài đặt</Link>
      <button role="menuitem" className="is-danger" onClick={() => { logout(); location.href = "/app/inbox"; }}><Icon name="logout" size={15}/>Đăng xuất</button>
    </div>}
  </div>;
}

function Crumbs() {
  const pathname = usePathname();
  const s = sectionFor(pathname);
  const [title, setTitle] = useState("");
  /* PageFrame báo tiêu đề cụ thể (trang chi tiết, trang ngoài menu) qua sự kiện, để breadcrumb không phải đoán. */
  useEffect(() => {
    const on = (e: Event) => setTitle((e as CustomEvent<string>).detail || "");
    window.addEventListener("cc:title", on); return () => window.removeEventListener("cc:title", on);
  }, []);
  return <nav className="ui-crumbs" aria-label="Vị trí">
    {s ? <>
      {title && title !== s.label ? <><Link href={s.href}>{s.label}</Link><Icon name="chevron-right" size={12}/><b>{title}</b></> : <b>{s.label}</b>}
    </> : <><Link href="/app/system">Trang khác</Link><Icon name="chevron-right" size={12}/><b>{title || "ClawCompany"}</b></>}
  </nav>;
}

function Bell() {
  const n = useCounts().inbox || 0;
  return <Link href="/app/inbox" className="ui-iconbtn" aria-label={n ? `Hộp việc, ${n} mục cần anh` : "Hộp việc"} data-testid="bell">
    <Icon name="bell" size={18}/>{n > 0 && <em className="ui-dot">{n > 9 ? "9+" : n}</em>}
  </Link>;
}

const BOTTOM = ["inbox", "os", "work", "team"];

function BottomNav({onMore}: {onMore: () => void}) {
  const pathname = usePathname();
  const current = sectionFor(pathname);
  const n = useCounts().inbox || 0;
  return <nav className="ui-bottomnav" aria-label="Điều hướng nhanh">
    {BOTTOM.map(k => { const s = SECTIONS.find(x => x.key === k)!;
      return <Link key={k} href={s.href} aria-current={current?.key === k ? "page" : undefined} data-testid={`bnav-${k}`}>
        <Icon name={s.icon} size={20}/><span>{k === "goals" ? "Mục tiêu" : s.label}</span>
        {k === "inbox" && n > 0 && <em className="ui-dot">{n > 9 ? "9+" : n}</em>}
      </Link>; })}
    <button onClick={onMore} aria-label="Mở toàn bộ menu" data-testid="bnav-more"
            aria-current={current && !BOTTOM.includes(current.key) ? "page" : undefined}><Icon name="menu" size={20}/><span>Thêm</span></button>
  </nav>;
}

export function Shell({children}: {children: ReactNode}) {
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  useEffect(() => { setDrawer(false); }, [pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(v => !v); }
      if (e.key === "Escape") setDrawer(false);
    };
    const onScroll = () => setScrolled(window.scrollY > 4);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, {passive: true});
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("scroll", onScroll); };
  }, []);
  /* Đoán trước: tải sẵn mã của các mục menu khi rảnh, chuyển trang tức thì. */
  useEffect(() => {
    const idle = (window as any).requestIdleCallback || ((fn: () => void) => setTimeout(fn, 1200));
    idle(() => SECTIONS.forEach(s => router.prefetch(s.href)));
  }, [router]);
  const close = () => setDrawer(false);

  return <ToastProvider>
    <div className={"ui-app" + (drawer ? " is-drawer" : "")}>
      <a href="#main" className="ui-skip">Bỏ qua tới nội dung</a>
      <aside className="ui-side" aria-label="Menu">
        <CompanySwitcher onNavigate={close}/>
        <button className="ui-side-search" onClick={() => { close(); setPalette(true); }} data-testid="open-palette">
          <Icon name="search" size={15}/><span>Tìm hoặc đi tới…</span><kbd>Ctrl&nbsp;K</kbd>
        </button>
        <SideNav onNavigate={close}/>
        <div className="ui-side-foot"><Account/></div>
      </aside>
      <button className="ui-drawer-scrim" aria-label="Đóng menu" onClick={close} tabIndex={drawer ? 0 : -1}/>

      <div className="ui-main">
        <header className={"ui-top" + (scrolled ? " is-scrolled" : "")}>
          <button className="ui-iconbtn ui-menu-btn" aria-label="Mở menu" onClick={() => setDrawer(true)} data-testid="open-drawer"><Icon name="menu" size={19}/></button>
          <Crumbs/>
          <button className="ui-search-btn" onClick={() => setPalette(true)} aria-label="Tìm kiếm (Ctrl K)">
            <Icon name="search" size={14}/><span>Tìm trang, việc, agent…</span><kbd>⌘K</kbd>
          </button>
          <div className="ui-top-actions">
            <span className="ui-mobile-search"><button className="ui-iconbtn" onClick={() => setPalette(true)} aria-label="Tìm kiếm"><Icon name="search" size={18}/></button></span>
            <Bell/>
          </div>
        </header>
        <main id="main" className="ui-content">
          <Suspense fallback={<SkeletonRows n={6} h={44}/>}>{children}</Suspense>
        </main>
      </div>
      <BottomNav onMore={() => setDrawer(true)}/>
      {palette && <CommandPalette onClose={() => setPalette(false)}/>}
    </div>
  </ToastProvider>;
}
