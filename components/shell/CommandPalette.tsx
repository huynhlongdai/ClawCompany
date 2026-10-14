"use client";
import {useRouter} from "next/navigation";
import {useEffect, useMemo, useRef, useState} from "react";
import {Icon, IconName} from "../Icon";
import {apiV17} from "../../lib/api";
import {LAB_PAGES, MORE_PAGES, SECTIONS} from "../../lib/nav";
import {useLab, useThemePref} from "../../lib/prefs";

/* ⌘K — đi tới MỌI trang: 8 mục + tab của chúng, trang ngoài menu, và (khi bật
   cờ) 27 trang Phòng thí nghiệm; cộng việc, agent, người lấy từ API; cộng vài
   lệnh nhanh. Bàn phím là đường chính: ↑↓ chọn, Enter mở, Esc đóng.
   Tải lười (next/dynamic) nên không nằm trong JS ban đầu của trang nào. */

type Hit = {id: string; label: string; hint: string; href?: string; run?: () => void; icon: IconName; kind: string; lab?: boolean; search: string};

const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();

let remoteCache: Hit[] | null = null;
async function loadRemote(): Promise<Hit[]> {
  if (remoteCache) return remoteCache;
  const [tasks, members] = await Promise.allSettled([apiV17.tasks(), apiV17.people()]);
  const out: Hit[] = [];
  if (tasks.status === "fulfilled") for (const t of tasks.value || []) out.push({
    id: "t" + t.id, kind: "Việc", label: t.title, icon: "check", href: `/app/work?peek=${t.id}`,
    hint: [`#${t.id}`, t.project_name, t.assignee_name].filter(Boolean).join(" · "), search: fold(`${t.id} ${t.title} ${t.project_name || ""} ${t.assignee_name || ""}`),
  });
  if (members.status === "fulfilled") for (const m of (members.value as any[]) || []) {
    const agent = m.member_type === "agent", name = m.name || m.display_name || `#${m.id}`;
    out.push({id: "m" + m.id, kind: agent ? "Agent" : "Người", label: name, icon: agent ? "sparkle" : "user", hint: m.role || "",
      href: agent ? `/app/agents/${m.id}` : "/app/team?tab=people", search: fold(`${name} ${m.role || ""}`)});
  }
  remoteCache = out;
  return out;
}

const PAGES: Hit[] = [
  ...SECTIONS.flatMap(s => [
    {id: "s" + s.key, kind: "Trang", label: s.label, icon: s.icon, href: s.href, hint: s.desc, search: fold(`${s.label} ${s.desc} ${s.keywords}`)},
    ...s.tabs.slice(1).map(t => ({id: "t" + t.href, kind: "Trang", label: `${s.label} › ${t.label}`, icon: s.icon, href: t.href, hint: t.desc || "",
      search: fold(`${s.label} ${t.label} ${s.keywords}`)})),
  ]),
  ...MORE_PAGES.map(p => ({id: "p" + p.href, kind: "Trang khác", label: p.label, icon: p.icon, href: p.href, hint: `${p.area} · ${p.desc}`,
    search: fold(`${p.label} ${p.desc} ${p.keywords || ""} ${p.area}`)})),
];
const LAB_HITS: Hit[] = LAB_PAGES.map(p => ({id: "l" + p.href, kind: "Phòng thí nghiệm", lab: true, label: p.label, icon: p.icon, href: p.href,
  hint: `${p.area} · ${p.desc}`, search: fold(`${p.label} ${p.desc} ${p.area} lab phong thi nghiem`)}));

export function CommandPalette({onClose}: {onClose: () => void}) {
  const router = useRouter();
  const [lab, setLab] = useLab();
  const [theme, setTheme] = useThemePref();
  const [q, setQ] = useState("");
  const [remote, setRemote] = useState<Hit[]>(remoteCache || []);
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    input.current?.focus();
    loadRemote().then(setRemote).catch(() => {});
    return () => { (opener.current as HTMLElement | null)?.focus?.(); };
  }, []);

  const actions: Hit[] = useMemo(() => [
    {id: "a-new", kind: "Lệnh", label: "Tạo việc mới", icon: "plus", href: "/app/work?new=1", hint: "Mở form tạo việc", search: fold("tao viec moi task new")},
    {id: "a-goal", kind: "Lệnh", label: "Giao mục tiêu cho Nina", icon: "target", href: "/app/strategy", hint: "Nina lập kế hoạch, anh duyệt", search: fold("muc tieu nina ke hoach goal")},
    {id: "a-theme", kind: "Lệnh", label: theme === "dark" ? "Chuyển giao diện sáng" : "Chuyển giao diện tối", icon: "sparkle",
     run: () => setTheme(theme === "dark" ? "light" : "dark"), hint: "Giao diện", search: fold("giao dien toi sang dark light theme")},
    {id: "a-lab", kind: "Lệnh", label: lab ? "Tắt Phòng thí nghiệm" : "Bật Phòng thí nghiệm", icon: "flag", run: () => setLab(!lab),
     hint: `${LAB_PAGES.length} trang ít dùng`, search: fold("phong thi nghiem lab bat tat")},
  ], [lab, theme, setLab, setTheme]);

  const hits = useMemo(() => {
    const f = fold(q.trim());
    if (!f) return SECTIONS.map(s => PAGES.find(p => p.id === "s" + s.key)!);
    const all = [...PAGES, ...(lab ? LAB_HITS : []), ...actions, ...remote];
    return all.filter(h => h.search.includes(f)).slice(0, 40);
  }, [q, remote, lab, actions]);

  useEffect(() => { setSel(0); }, [q]);
  useEffect(() => { list.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({block: "nearest"}); }, [sel]);

  const go = (h?: Hit) => { if (!h) return; onClose(); if (h.run) h.run(); else if (h.href) router.push(h.href); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(hits[sel]); }
    else if (e.key === "Tab") { e.preventDefault(); }
  };

  return <div className="ui-palette-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="ui-palette" role="dialog" aria-modal="true" aria-label="Tìm kiếm và đi tới" onKeyDown={onKey} data-testid="palette">
      <div className="ui-palette-input">
        <Icon name="search" size={17}/>
        <input ref={input} value={q} onChange={e => setQ(e.target.value)} placeholder="Gõ tên trang, việc, agent hoặc lệnh…" aria-label="Tìm kiếm"
               role="combobox" aria-expanded="true" aria-controls="ui-palette-list" autoComplete="off" spellCheck={false}
               aria-activedescendant={hits[sel] ? "ui-hit-" + sel : undefined}/>
        <kbd>Esc</kbd>
      </div>
      <div className="ui-palette-list" id="ui-palette-list" role="listbox" ref={list}>
        {!q && <p className="ui-palette-section">Đi tới</p>}
        {hits.length === 0 && <p className="ui-palette-empty">Không có kết quả cho “{q}”.{!lab && " Trang ít dùng đang ẩn — gõ “phòng thí nghiệm” để bật."}</p>}
        {hits.map((h, i) =>
          <button key={h.id} id={"ui-hit-" + i} data-i={i} role="option" aria-selected={i === sel}
                  className={"ui-hit" + (i === sel ? " is-sel" : "")} onMouseMove={() => setSel(i)} onClick={() => go(h)}>
            <Icon name={h.icon} size={16}/>
            <span className="ui-hit-label">{h.label}</span>
            <span className="ui-hit-hint">{h.hint}</span>
            <span className={"ui-hit-kind" + (h.lab ? " is-lab" : "")}>{h.kind}</span>
          </button>)}
      </div>
      <div className="ui-palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> chọn</span><span><kbd>Enter</kbd> mở</span><span><kbd>Esc</kbd> đóng</span>
        <span style={{marginLeft: "auto"}}>{lab ? `Phòng thí nghiệm: bật (${LAB_PAGES.length} trang)` : "Phòng thí nghiệm: tắt"}</span></div>
    </div>
  </div>;
}
