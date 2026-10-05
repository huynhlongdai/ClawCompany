"use client";
import {useRouter} from "next/navigation";
import {useEffect, useMemo, useRef, useState} from "react";
import {Icon, IconName} from "./Icon";
import {apiV17} from "../lib/api";
import {NAV, groupLabel} from "../lib/nav";

/* Tìm kiếm ⌘K. Một ô, ba nguồn: trang (lib/nav.ts), nhiệm vụ và người/agent
   (v17 workspace). Bàn phím là đường chính: ↑↓ chọn, Enter mở, Esc đóng.
   Không có animation khi chọn bằng phím — thao tác lặp hàng trăm lần một
   ngày thì chuyển động chỉ làm chậm. */

type Hit = {id: string; label: string; hint: string; href: string; icon: IconName; kind: string};

const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();

let remoteCache: Hit[] | null = null;

async function loadRemote(): Promise<Hit[]> {
  if (remoteCache) return remoteCache;
  const [tasks, members] = await Promise.allSettled([apiV17.tasks(), apiV17.people()]);
  const out: Hit[] = [];
  if (tasks.status === "fulfilled") for (const t of tasks.value || []) out.push({
    id: "t" + t.id, kind: "Nhiệm vụ", label: t.title, icon: "check",
    hint: [t.project_name, t.assignee_name].filter(Boolean).join(" · "), href: `/app/tasks/${t.id}`,
  });
  if (members.status === "fulfilled") for (const m of (members.value as any[]) || []) out.push({
    id: "m" + m.id, kind: m.member_type === "agent" ? "Agent" : "Người", label: m.name || m.display_name || `#${m.id}`,
    icon: m.member_type === "agent" ? "sparkle" : "user", hint: m.role || "",
    href: m.member_type === "agent" ? "/app/os?tab=agents" : "/app/os?tab=people",
  });
  remoteCache = out;
  return out;
}

const PAGES: Hit[] = NAV.map(n => ({
  id: "p" + n.href, kind: n.group === "system" ? "Công cụ" : "Trang", label: n.label, icon: n.icon,
  hint: n.area || groupLabel(n.group) || n.desc, href: n.href,
  // keywords + desc giúp gõ "budget" vẫn ra "Ngân sách".
  ...({search: fold([n.label, n.desc, n.keywords || "", n.area || ""].join(" "))} as any),
}));

export function CommandPalette({onClose}: {onClose: () => void}) {
  const router = useRouter();
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

  const hits = useMemo(() => {
    const f = fold(q.trim());
    const all = [...PAGES, ...remote];
    if (!f) return PAGES.filter(p => p.kind === "Trang").slice(0, 10);
    return all.filter(h => ((h as any).search || fold(h.label + " " + h.hint)).includes(f)).slice(0, 30);
  }, [q, remote]);

  useEffect(() => { setSel(0); }, [q]);
  useEffect(() => {
    list.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({block: "nearest"});
  }, [sel]);

  const go = (h?: Hit) => { if (!h) return; onClose(); router.push(h.href); };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(hits[sel]); }
    else if (e.key === "Tab") { e.preventDefault(); }
  };

  return <div className="ui-palette-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="ui-palette" role="dialog" aria-modal="true" aria-label="Tìm kiếm" onKeyDown={onKey}>
      <div className="ui-palette-input">
        <Icon name="search" size={16}/>
        <input ref={input} value={q} onChange={e => setQ(e.target.value)}
               placeholder="Gõ tên trang, nhiệm vụ, agent…" aria-label="Tìm kiếm"
               role="combobox" aria-expanded="true" aria-controls="ui-palette-list"
               aria-activedescendant={hits[sel] ? "ui-hit-" + sel : undefined}/>
        <kbd>Esc</kbd>
      </div>
      <div className="ui-palette-list" id="ui-palette-list" role="listbox" ref={list}>
        {!q && <p className="ui-palette-section">Đi tới</p>}
        {hits.length === 0 && <p className="ui-palette-empty">Không có kết quả cho “{q}”.</p>}
        {hits.map((h, i) =>
          <button key={h.id} id={"ui-hit-" + i} data-i={i} role="option" aria-selected={i === sel}
                  className={"ui-hit" + (i === sel ? " is-sel" : "")}
                  onMouseMove={() => setSel(i)} onClick={() => go(h)}>
            <Icon name={h.icon} size={16}/>
            <span className="ui-hit-label">{h.label}</span>
            <span className="ui-hit-hint">{h.hint}</span>
            <span className="ui-hit-kind">{h.kind}</span>
          </button>)}
      </div>
      <div className="ui-palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> chọn</span><span><kbd>Enter</kbd> mở</span><span><kbd>Esc</kbd> đóng</span></div>
    </div>
  </div>;
}
