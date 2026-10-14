"use client";
// M4a — Công việc: danh sách + bảng + side-peek kiểu Linear, dòng thời gian lượt chạy kèm
// chi phí, review chéo, chạy ngay. Một nguồn dữ liệu: /api/work (services/work_board.py).
import Link from "next/link";
import {usePathname, useRouter, useSearchParams} from "next/navigation";
import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {Icon} from "./Icon";
import {apiWork, errorText} from "../lib/api";
import {refreshCounts} from "../lib/counts";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {ProjectsView} from "./work/ProjectsView";
import {t as tr, lazy, intlLocale} from "../lib/i18n";
import {viStatus} from "../lib/labels";

type Who = {id: number; name: string; type: string; role?: string; lifecycle?: string | null} | null;
export type WorkItem = {
  id: number; title: string; status: string; status_vi: string; priority: string; priority_vi: string;
  project: {id: number; name: string} | null; company: {id: number; name: string} | null;
  assignee: Who; department: {id: number; name: string} | null; routed_to_department: boolean;
  due_at: string | null; overdue: boolean; updated_at: string | null; revision: string;
  runs: {count: number; cost_usd: number; tokens: number; running: boolean; last_status: string | null; failed: number};
  review: {needed: boolean; state: string | null; state_vi: string; reviewer: Who; reviewers: Who[]; round: number};
  blocked_by: number;
};

const BOARD = ["backlog", "todo", "in_progress", "review", "blocked", "done"];
const LIST_ORDER = ["in_progress", "review", "blocked", "todo", "backlog", "done", "cancelled"];
const PRIO_RANK: Record<string, number> = {urgent: 0, high: 1, medium: 2, low: 3};
const LC_VI: Record<string, string> = lazy(() => ({paused: tr("work.tam_dung"), retired: tr("work.da_nghi"), runtime_missing: tr("work.cho_gateway")}));

export function money(v?: number | null) {
  const n = Number(v || 0);
  if (!n) return "$0";
  return "$" + (n < 0.01 ? n.toFixed(4) : n < 1 ? n.toFixed(3) : n.toFixed(2));
}
function stamp(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return tr("work.vua_xong");
  if (s < 3600) return tr("work.phut_truoc", {p0: Math.floor(s / 60)});
  if (s < 86400) return tr("work.gio_truoc", {p0: Math.floor(s / 3600)});
  return d.toLocaleDateString(intlLocale(), {day: "2-digit", month: "2-digit"});
}
function clock(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString(intlLocale(), {hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit"});
}
function dur(s?: number | null) {
  if (s === null || s === undefined) return "";
  if (s < 60) return tr("work.giay", {p0: Math.round(s)});
  return tr("work.phut_giay", {p0: Math.floor(s / 60), p1: Math.round(s % 60)});
}
function dueLabel(iso?: string | null) {
  if (!iso) return "";
  return new Date(iso.slice(0, 10) + "T00:00:00").toLocaleDateString(intlLocale(), {day: "2-digit", month: "2-digit"});
}

export function Avatar({who}: {who: Who}) {
  if (!who) return <span className="ui-ava is-none" aria-hidden="true">?</span>;
  return <span className={"ui-ava " + (who.type === "agent" ? "is-agent" : "is-human")} aria-hidden="true">
    {who.type === "agent" ? <Icon name="sparkle" size={11} strokeWidth={2}/> : who.name.slice(0, 1).toUpperCase()}
  </span>;
}

function PrioIcon({p}: {p: string}) {
  const bars = p === "urgent" ? 4 : p === "high" ? 3 : p === "medium" ? 2 : 1;
  return <span className={"wkPrio is-" + p} aria-label={tr("work.uu_tien", {p0: ({urgent: "khẩn", high: "cao", medium: "vừa", low: "thấp"} as any)[p] || p})}>
    {p === "urgent" ? <b>!</b> : [1, 2, 3].map(i => <i key={i} className={i <= bars ? "on" : ""}/>)}
  </span>;
}

function Badges({t}: {t: WorkItem}) {
  return <>
    {t.runs.running && <span className="ui-status is-running"><span className="ui-pulse"/>{tr("work.dang_chay")}</span>}
    {!t.runs.running && t.runs.last_status === "failed" && <span className="wkBadge is-failed">{tr("work.luot_cuoi_loi")}</span>}
    {t.review.needed && t.status === "review" && <span className="wkBadge is-review">
      {t.review.reviewer ? `${t.review.reviewer.name} review` : t.review.state_vi}</span>}
    {t.review.needed && t.status !== "review" && t.status !== "done" && <span className="wkBadge" title={tr("work.co_review_cheo_truoc_khi")}>{tr("work.review_cheo")}</span>}
    {t.blocked_by > 0 && <span className="wkBadge is-blocked">{tr("work.cho")} {t.blocked_by} {tr("work.viec")}</span>}
    {t.due_at && <span className={"wkBadge" + (t.overdue ? " is-overdue" : "")}><Icon name="clock" size={11}/>{dueLabel(t.due_at)}</span>}
  </>;
}

// ------------------------------------------------------------------ trang chính

/* Nhãn trạng thái theo ngôn ngữ (backend trả status_vi tiếng Việt cố định). */
const LABEL: Record<string, string> = lazy(() => ({backlog: tr("work.ton_dong"), todo: tr("work.can_lam"), in_progress: tr("work.dang_lam_2"), review: tr("work.cho_duyet_2"), blocked: tr("work.bi_chan_2"), done: tr("work.xong_hoa"), cancelled: tr("work.da_huy")}));
const statusLabel = (t: {status: string; status_vi?: string}) => LABEL[t.status] || t.status_vi || t.status;
const prioLabel = (p: {key: string; label: string}) => ({urgent: 1, high: 1, medium: 1, low: 1} as any)[p.key] ? viStatus(p.key) : p.label;

export function WorkBoard() {
  const sp = useSearchParams();
  /* Công việc › Dự án là một tab riêng (route ?view=projects), không phải kiểu xem của danh sách việc. */
  if (sp.get("view") === "projects") return <ProjectsView/>;
  return <WorkTasks/>;
}

function WorkTasks() {
  const router = useRouter(), pathname = usePathname(), sp = useSearchParams();
  const view = sp.get("view") === "board" ? "board" : "list";
  const peek = Number(sp.get("peek") || 0) || null;
  const [assignee, setAssignee] = useState(sp.get("assignee") || "");
  const [dept, setDept] = useState(sp.get("dept") || "");
  const [prio, setPrio] = useState(sp.get("prio") || "");
  const [q, setQ] = useState(sp.get("q") || "");
  const [showDone, setShowDone] = useState(false);
  const [data, setData] = useState<any>(null), [meta, setMeta] = useState<any>(null);
  const [error, setError] = useState<unknown>(null), [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(sp.get("new") === "1");
  const [sel, setSel] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  const setParam = useCallback((patch: Record<string, string | null>) => {
    const p = new URLSearchParams(sp.toString());
    Object.entries(patch).forEach(([k, v]) => v ? p.set(k, v) : p.delete(k));
    router.replace(`${pathname}${p.toString() ? `?${p}` : ""}`, {scroll: false});
  }, [sp, router, pathname]);

  const load = useCallback(async () => {
    try {
      setData(await apiWork.list({assignee, department_id: dept, priority: prio, q: q.trim()}));
      setError(null);
    } catch (e) { setError(e); }
  }, [assignee, dept, prio, q]);
  useEffect(() => { const h = setTimeout(load, q ? 250 : 0); return () => clearTimeout(h); }, [load, q]);
  useEffect(() => { apiWork.meta().then(setMeta).catch(e => setError(e)); }, []);
  useEffect(() => {  // có lượt đang chạy → làm mới 10 giây/lần
    if (!data?.items?.some((t: WorkItem) => t.runs.running || t.status === "review")) return;
    const h = setInterval(load, 10000); return () => clearInterval(h);
  }, [data, load]);
  useEffect(() => { setParam({assignee: assignee || null, dept: dept || null, prio: prio || null, q: q || null}); // eslint-disable-next-line
  }, [assignee, dept, prio, q]);

  const items: WorkItem[] = data?.items || [];
  const flat = useMemo(() => {
    const order = view === "list" ? LIST_ORDER : BOARD;
    return [...items].filter(t => showDone || view === "board" || !["done", "cancelled"].includes(t.status))
      .sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status)
        || (PRIO_RANK[a.priority] ?? 9) - (PRIO_RANK[b.priority] ?? 9) || b.id - a.id);
  }, [items, view, showDone]);

  useEffect(() => {  // phím tắt: c tạo việc, / tìm, j/k chọn, Enter mở, Esc đóng
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "c" && meta?.caps?.create) { e.preventDefault(); setCreating(true); }
      else if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); }
      else if (view === "list" && (e.key === "j" || e.key === "ArrowDown")) { e.preventDefault(); setSel(i => Math.min(i + 1, flat.length - 1)); }
      else if (view === "list" && (e.key === "k" || e.key === "ArrowUp")) { e.preventDefault(); setSel(i => Math.max(i - 1, 0)); }
      else if (e.key === "Enter" && view === "list" && flat[sel]) setParam({peek: String(flat[sel].id)});
      else if (e.key === "Escape" && peek) setParam({peek: null});
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [flat, sel, view, peek, meta, setParam]);

  async function move(t: WorkItem, status: string) {
    if (t.status === status) return;
    const before = data;
    setData((d: any) => ({...d, items: d.items.map((x: WorkItem) => x.id === t.id ? {...x, status} : x)}));
    try { await apiWork.move(t.id, status, t.revision); setNotice(""); refreshCounts(); load(); }
    catch (e: any) {
      setData(before);
      setNotice(tr("work.khong_chuyen_duoc", {p0: t.title, p1: errorText(e)}));
      if (e?.code === "stale_revision") load();
    }
  }

  const counts = data?.counts || {};
  const depts = (meta?.departments || []) as any[];
  const filtered = !!(assignee || dept || prio || q);
  return <div className="wkPage">
    <div className="ui-statline" aria-label={tr("work.tom_tat")}>
      <span><b className="ui-num">{counts.in_progress || 0}</b> {tr("work.dang_lam")}</span>
      <span><b className="ui-num">{counts.review || 0}</b> {tr("work.cho_duyet")}</span>
      <span className={counts.blocked ? "is-blocked" : ""}><b className="ui-num">{counts.blocked || 0}</b> {tr("work.bi_chan")}</span>
      <span><b className="ui-num">{(counts.todo || 0) + (counts.backlog || 0)}</b> {tr("work.chua_lam")}</span>
      <span><b className="ui-num">{counts.done || 0}</b> {tr("work.xong")}</span>
      <span className="wkCost" title={tr("work.tong_chi_phi_luot_chay")}>
        <Icon name="coins" size={13}/>{money(items.reduce((s, t) => s + (t.runs.cost_usd || 0), 0))}</span>
    </div>

    <div className="ui-toolbar wkToolbar">
      <label className="wkSearch"><Icon name="search" size={14}/>
        <input ref={searchRef} value={q} onChange={e => setQ(e.target.value)} placeholder={tr("work.tim_viec_hoac_so")}
               aria-label={tr("work.tim_viec")} data-testid="wk-search"/></label>
      <select value={assignee} onChange={e => setAssignee(e.target.value)} aria-label={tr("work.nguoi_nhan")} className="wkSelect" data-testid="wk-filter-assignee">
        <option value="">{tr("work.moi_nguoi_nhan")}</option>
        {meta?.me && <option value="me">{tr("work.viec_cua_toi")}</option>}
        <option value="agent">{tr("work.agent_lam")}</option><option value="human">{tr("work.nguoi_lam")}</option><option value="none">{tr("work.chua_giao")}</option>
        <optgroup label={tr("work.tung_nguoi")}>{(meta?.members || []).map((m: any) =>
          <option key={m.id} value={String(m.id)}>{m.name}{m.type === "agent" ? " (agent)" : ""}</option>)}</optgroup>
      </select>
      {depts.length > 0 && <select value={dept} onChange={e => setDept(e.target.value)} aria-label={tr("work.phong_ban")} className="wkSelect">
        <option value="">{tr("work.moi_phong")}</option>{depts.map(d => <option key={d.id} value={String(d.id)}>{d.name}</option>)}</select>}
      <select value={prio} onChange={e => setPrio(e.target.value)} aria-label={tr("work.uu_tien_2")} className="wkSelect">
        <option value="">{tr("work.moi_uu_tien")}</option><option value="urgent,high">{tr("work.khan_cao")}</option>
        {(meta?.priorities || []).map((p: any) => <option key={p.key} value={p.key}>{prioLabel(p)}</option>)}</select>
      {view === "list" && <button className="ui-chip" aria-pressed={showDone} onClick={() => setShowDone(v => !v)}>{tr("work.hien_viec_da_xong")}</button>}
      {filtered && <button className="ui-btn is-ghost is-sm" onClick={() => { setAssignee(""); setDept(""); setPrio(""); setQ(""); }}>{tr("work.bo_loc")}</button>}
      {meta?.caps?.create && <button className="ui-btn is-primary wkNew" onClick={() => setCreating(true)} data-testid="wk-new">
        <Icon name="plus" size={14}/>{tr("work.tao_viec")} <kbd>C</kbd></button>}
    </div>

    {error ? <ErrorBanner error={error} onRetry={load} context={tr("work.tai_danh_sach_viec")}/> : null}
    {notice && <div className="ui-banner is-error" role="alert" data-testid="wk-notice"><Icon name="alert" size={16}/><span>{notice}</span>
      <button className="ui-btn is-ghost" onClick={() => setNotice("")}>{tr("work.dong")}</button></div>}

    {!data && !error && <SkeletonRows n={6} h={40}/>}
    {data && items.length === 0 && <EmptyState mood={filtered ? "ngu" : "chao"} title={filtered ? tr("work.khong_co_viec_nao_khop") : tr("work.chua_co_viec_nao")}
      action={!filtered && meta?.caps?.create ? <button className="ui-btn is-primary" onClick={() => setCreating(true)}>{tr("work.tao_viec")}</button> : undefined}>
      {filtered ? tr("work.bo_bot_bo_loc_de") : tr("work.tao_viec_dau_tien_va")}
    </EmptyState>}

    {data && items.length > 0 && view === "list" && <ListView items={flat} sel={sel} setSel={setSel}
      open={id => setParam({peek: String(id)})} active={peek}/>}
    {data && items.length > 0 && view === "board" && <BoardView items={flat} move={move} open={id => setParam({peek: String(id)})}/>}

    {peek && <TaskPeek id={peek} meta={meta} onClose={() => setParam({peek: null})} onChanged={() => { load(); refreshCounts(); }}/>}
    {creating && meta && <CreateTask meta={meta} onClose={() => { setCreating(false); if (sp.get("new")) setParam({new: null}); }}
      onCreated={id => { setCreating(false); load(); refreshCounts(); setParam({peek: String(id), new: null}); }}/>}
  </div>;
}

function ListView({items, sel, setSel, open, active}: {items: WorkItem[]; sel: number; setSel: (i: number) => void;
  open: (id: number) => void; active: number | null}) {
  const groups = LIST_ORDER.map(s => ({s, rows: items.filter(t => t.status === s)})).filter(g => g.rows.length);
  let idx = -1;
  return <div className="wkList" role="list" data-testid="wk-list">
    {groups.map(g => <section key={g.s} className="wkGroup">
      <header className="wkGroupHead"><span className={"ui-sdot is-" + g.s}/><h2>{statusLabel(g.rows[0])}</h2><span className="ui-num">{g.rows.length}</span></header>
      {g.rows.map(t => { idx += 1; const i = idx;
        return <button key={t.id} role="listitem" className={"wkRow" + (i === sel ? " is-sel" : "") + (active === t.id ? " is-open" : "")}
                       onClick={() => { setSel(i); open(t.id); }} data-testid={`wk-row-${t.id}`}>
          <PrioIcon p={t.priority}/>
          <span className="ui-mono wkId">#{t.id}</span>
          <span className="wkTitle">{t.title}</span>
          <span className="wkBadges"><Badges t={t}/></span>
          <span className="wkMeta">{t.department && <span className="wkDept">{t.department.name}</span>}</span>
          <span className="wkWho"><Avatar who={t.assignee}/>{t.assignee ? t.assignee.name : t.routed_to_department ? tr("work.cho_truong_phong") : tr("work.chua_giao")}</span>
          <span className="wkCostCell ui-num" title={tr("work.luot_chay", {p0: t.runs.count})}>{t.runs.count ? money(t.runs.cost_usd) : ""}</span>
          <span className="wkWhen">{stamp(t.updated_at)}</span>
        </button>; })}
    </section>)}
  </div>;
}

function BoardView({items, move, open}: {items: WorkItem[]; move: (t: WorkItem, s: string) => void; open: (id: number) => void}) {
  const [drag, setDrag] = useState<number | null>(null), [over, setOver] = useState<string | null>(null);
  const [menu, setMenu] = useState<{t: WorkItem; r: DOMRect} | null>(null);
  return <div className="ui-board wkBoard" data-testid="wk-board">
    {BOARD.map(s => { const rows = items.filter(t => t.status === s);
      return <section key={s} className={"ui-col" + (over === s ? " is-over" : "") + (rows.length ? "" : " is-empty")}
                      aria-label={tr("work.viec_2", {p0: LABEL[s], p1: rows.length})} data-testid={`wk-col-${s}`}
                      onDragOver={e => { if (drag !== null) { e.preventDefault(); setOver(s); } }}
                      onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(null); }}
                      onDrop={e => { e.preventDefault(); setOver(null); const t = items.find(x => x.id === Number(e.dataTransfer.getData("text/plain"))); if (t) move(t, s); }}>
        <header className="ui-col-head"><span className={"ui-sdot is-" + s}/><h2>{LABEL[s]}</h2><span className="ui-num">{rows.length}</span></header>
        <div className="ui-col-body">
          {rows.map(t => <article key={t.id} className={"ui-card" + (drag === t.id ? " is-dragging" : "")} draggable data-testid={`wk-card-${t.id}`}
                                  onDragStart={e => { e.dataTransfer.setData("text/plain", String(t.id)); e.dataTransfer.effectAllowed = "move"; setDrag(t.id); }}
                                  onDragEnd={() => setDrag(null)}>
            <div className="ui-card-top">
              <button className="ui-card-title wkCardOpen" onClick={() => open(t.id)}>{t.title}</button>
              <div className="ui-card-menu">
                <button className="ui-iconbtn is-sm" aria-label={tr("work.chuyen_trang_thai", {p0: t.title})} aria-haspopup="menu"
                        onClick={e => { const r = e.currentTarget.getBoundingClientRect(); setMenu(m => m?.t.id === t.id ? null : {t, r}); }}>
                  <Icon name="more" size={16} strokeWidth={2.4}/></button>
              </div>
            </div>
            <p className="ui-card-meta"><PrioIcon p={t.priority}/><span className="ui-mono">#{t.id}</span>
              {t.project && <><span>·</span><span className="ui-ellipsis">{t.project.name}</span></>}</p>
            <div className="wkBadges"><Badges t={t}/></div>
            <div className="ui-card-foot">
              <span className="ui-who"><Avatar who={t.assignee}/>{t.assignee?.name || (t.routed_to_department ? tr("work.cho_truong_phong") : tr("work.chua_giao"))}</span>
              {t.runs.count > 0 && <span className="wkCostCell ui-num">{money(t.runs.cost_usd)}</span>}
            </div>
          </article>)}
          {!rows.length && <p className="ui-col-empty">{tr("work.trong")}</p>}
        </div>
      </section>; })}
    {menu && <MoveMenu t={menu.t} anchor={menu.r} onClose={() => setMenu(null)} onMove={s => { const t = menu.t; setMenu(null); move(t, s); }}/>}
  </div>;
}

const NEXT: Record<string, string[]> = {backlog: ["todo", "cancelled"], todo: ["in_progress", "backlog", "cancelled"],
  in_progress: ["review", "todo", "blocked", "cancelled"], review: ["done", "in_progress", "cancelled"],
  blocked: ["in_progress", "todo", "cancelled"], done: ["review"], cancelled: ["backlog"]};
const SV: Record<string, string> = lazy(() => ({backlog: tr("work.ton_dong"), todo: tr("work.can_lam"), in_progress: tr("work.dang_lam_2"), review: tr("work.cho_duyet_2"), blocked: tr("work.bi_chan_2"), done: "Xong", cancelled: tr("work.da_huy")}));

function MoveMenu({t, anchor, onMove, onClose}: {t: WorkItem; anchor: DOMRect; onMove: (s: string) => void; onClose: () => void}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const out = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    setTimeout(() => document.addEventListener("mousedown", out));
    document.addEventListener("keydown", esc); window.addEventListener("scroll", onClose, true);
    return () => { document.removeEventListener("mousedown", out); document.removeEventListener("keydown", esc); window.removeEventListener("scroll", onClose, true); };
  }, [onClose]);
  const W = 200, left = Math.max(8, Math.min(anchor.right - W, window.innerWidth - W - 8));
  return <div ref={ref} className="ui-pop" role="menu" style={{position: "fixed", top: anchor.bottom + 4, left, width: W, zIndex: 60}}>
    <p className="ui-pop-head">{tr("work.chuyen_sang")}</p>
    {(NEXT[t.status] || []).map(s => <button key={s} role="menuitem" className="ui-move" onClick={() => onMove(s)}>
      <span className={"ui-sdot is-" + s}/>{SV[s]}</button>)}
  </div>;
}

// ------------------------------------------------------------------ side-peek

export function TaskPeek({id, meta, onClose, onChanged}: {id: number; meta: any; onClose: () => void; onChanged: () => void}) {
  const [t, setT] = useState<any>(null), [error, setError] = useState(""), [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"timeline" | "review" | "desc">("timeline");
  const [busy, setBusy] = useState(false), [title, setTitle] = useState("");
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try { const d = await apiWork.get(id); setT(d); setTitle(d.title); setError(""); }
    catch (e) { setError(errorText(e, tr("work.khong_tai_duoc_viec"))); }
  }, [id]);
  useEffect(() => { setT(null); setMsg(""); load(); }, [load]);
  useEffect(() => { panel.current?.focus(); }, [id]);
  useEffect(() => {
    if (!t || !(t.totals?.running || (t.status === "review" && t.review?.reviewer?.type === "agent"))) return;
    const h = setInterval(load, 5000); return () => clearInterval(h);
  }, [t, load]);

  async function act(fn: () => Promise<any>, ok = "") {
    setBusy(true); setMsg("");
    try { const out = await fn(); if (out?.task) setT(out.task); else if (out?.id) { setT(out); setTitle(out.title); }
      if (ok || out?.message) setMsg(out?.message || ok); onChanged(); }
    catch (e: any) { setMsg(errorText(e)); if (e?.code === "stale_revision") load(); }
    finally { setBusy(false); }
  }
  const patch = (body: any) => act(() => apiWork.update(id, {expected_revision: t.revision, ...body}));

  const members = (meta?.members || []) as any[];
  const canRun = t?.assignee?.type === "agent" && ["backlog", "todo", "in_progress"].includes(t?.status) && !t?.totals?.running;
  return <div className="wkPeekWrap" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="wkPeek" role="dialog" aria-modal="false" aria-label={t ? tr("work.viec_3", {p0: t.id, p1: t.title}) : tr("work.chi_tiet_viec")}
           tabIndex={-1} ref={panel} data-testid="wk-peek">
      <header className="wkPeekHead">
        <span className="ui-mono">#{id}</span>
        {t?.project && <span className="wkCrumb">{t.company?.name ? `${t.company.name} · ` : ""}{t.project.name}</span>}
        <span className="wkGrow"/>
        <Link href={`/app/tasks/${id}`} className="ui-btn is-ghost is-sm" title={tr("work.so_ghi_ban_giao_goi")}>{tr("work.trang_day_du")}</Link>
        <button className="ui-iconbtn" onClick={onClose} aria-label={tr("work.dong_esc")} data-testid="wk-peek-close"><Icon name="x" size={16}/></button>
      </header>
      {error && <div className="ui-banner is-error"><Icon name="alert" size={16}/><span>{error}</span><button className="ui-btn is-ghost" onClick={load}>{tr("work.thu_lai")}</button></div>}
      {!t && !error && <div className="wkPeekBody"><div className="ui-skel" style={{height: 28}}/><div className="ui-skel" style={{height: 120}}/></div>}
      {t && <div className="wkPeekBody">
        <input className="wkTitleEdit" value={title} onChange={e => setTitle(e.target.value)} aria-label={tr("work.ten_viec")}
               onBlur={() => { if (title.trim() && title !== t.title) patch({title}); else setTitle(t.title); }}
               onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setTitle(t.title); (e.target as HTMLInputElement).blur(); } }}/>
        <div className="wkProps">
          <label>{tr("work.trang_thai")}<select value={t.status} disabled={busy} data-testid="wk-peek-status"
            onChange={e => act(() => apiWork.move(id, e.target.value, t.revision))}>
            <option value={t.status}>{statusLabel(t)}</option>
            {t.next.map((n: any) => <option key={n.key} value={n.key}>→ {n.label}</option>)}</select></label>
          <label>{tr("work.uu_tien_2")}<select value={t.priority} disabled={busy} onChange={e => patch({priority: e.target.value})}>
            {(meta?.priorities || []).map((p: any) => <option key={p.key} value={p.key}>{prioLabel(p)}</option>)}</select></label>
          <label>{tr("work.nguoi_nhan")}<select value={t.assignee?.id || ""} disabled={busy} data-testid="wk-peek-assignee"
            onChange={e => patch({assignee_member_id: e.target.value ? Number(e.target.value) : null})}>
            <option value="">{t.routed_to_department ? tr("work.cho_truong_phong_2", {p0: t.department?.name || ""}) : tr("work.chua_giao")}</option>
            {t.assignee && !members.some(m => m.id === t.assignee.id) && <option value={t.assignee.id}>{t.assignee.name}</option>}
            {members.filter(m => m.assignable).map(m => <option key={m.id} value={m.id}>{m.name}{m.type === "agent" ? " (agent)" : ""}</option>)}
          </select></label>
          <label>{tr("work.han_chot")}<input type="date" value={(t.due_at || "").slice(0, 10)} disabled={busy}
            onChange={e => patch({due_at: e.target.value || null})}/></label>
        </div>
        {t.assignee?.lifecycle && t.assignee.lifecycle !== "active" && <p className="wkWarn">
          {t.assignee.name} {tr("work.dang")} {LC_VI[t.assignee.lifecycle] || t.assignee.lifecycle} {tr("work.khong_nhan_luot_moi_giao")} <Link href={`/app/agents/${t.assignee.id}`}>{tr("work.ho_so_agent")}</Link>.</p>}
        {t.blocked_by.length > 0 && <p className="wkWarn">{tr("work.dang_cho")} {t.blocked_by.map((b: any) => `#${b.id} ${b.title} (${b.status_vi})`).join(", ")}.</p>}

        <div className="wkTotals" data-testid="wk-totals">
          <span><b className="ui-num">{t.totals.runs}</b> {tr("work.luot_chay_2")}{t.totals.failed ? tr("work.loi", {p0: t.totals.failed}) : ""}</span>
          <span title={tr("work.luot_chay_review", {p0: money(t.totals.run_cost_usd), p1: money(t.totals.review_cost_usd)})}><b className="ui-num">{money(t.totals.cost_usd)}</b> {tr("work.chi_phi")}</span>
          <span><b className="ui-num">{(t.totals.tokens_in + t.totals.tokens_out).toLocaleString(intlLocale())}</b> token</span>
          {t.review.needed && <span><b className="ui-num">{t.totals.review_rounds}</b> {tr("work.vong_review")}</span>}
          <span className="wkGrow"/>
          {t.assignee?.type === "agent" && <button className="ui-btn is-primary is-sm" disabled={busy || !canRun} data-testid="wk-run"
            title={canRun ? tr("work.gui_viec_cho_agent_ngay") : t.totals.running ? tr("work.dang_co_luot_chay") : tr("work.chi_chay_duoc_khi_ton")}
            onClick={() => act(() => apiWork.run(id))}><Icon name="play" size={13}/>{t.totals.running ? tr("work.dang_chay_2") : tr("work.chay_ngay")}</button>}
        </div>
        {msg && <p className="wkMsg" role="status" data-testid="wk-peek-msg">{msg}</p>}

        <div className="ui-seg wkTabs" role="tablist">
          <button role="tab" aria-selected={tab === "timeline"} onClick={() => setTab("timeline")}>{tr("work.dong_thoi_gian")}</button>
          <button role="tab" aria-selected={tab === "review"} onClick={() => setTab("review")} data-testid="wk-tab-review">
            Review{t.review.needed ? ` · ${t.review.state_vi || tr("work.chua_toi")}` : ""}</button>
          <button role="tab" aria-selected={tab === "desc"} onClick={() => setTab("desc")}>{tr("work.mo_ta")}</button>
        </div>
        {tab === "timeline" && <Timeline items={t.timeline}/>}
        {tab === "review" && <ReviewTab t={t} meta={meta} busy={busy} act={act}/>}
        {tab === "desc" && <DescTab t={t} busy={busy} patch={patch}/>}
      </div>}
    </aside>
  </div>;
}

function Timeline({items}: {items: any[]}) {
  if (!items.length) return <p className="ui-empty-line">{tr("work.chua_co_gi_xay_ra")}</p>;
  return <ol className="wkTimeline" data-testid="wk-timeline">
    {[...items].reverse().map((e, i) => {
      if (e.type === "event") return <li key={i} className="wkEv is-event"><span className="wkDot"/>
        <span>{e.label}{e.who ? ` · ${e.who.name}` : ""}{e.reason && !["changes_requested", "execution_policy_approved"].includes(e.reason) ? ` — ${e.reason}` : ""}</span>
        <time>{clock(e.at)}</time></li>;
      if (e.type === "entry") return <li key={i} className="wkEv is-entry"><span className="wkDot"/>
        <div><b>{e.kind_vi}</b>{e.who ? ` · ${e.who.name}` : ""}: {e.summary}
          {e.detail && <details><summary>{tr("work.chi_tiet")}</summary><pre>{e.detail}</pre></details>}</div><time>{clock(e.at)}</time></li>;
      if (e.type === "review_room") return <li key={i} className="wkEv is-run" data-testid="wk-review-room"><span className="wkDot is-review"/>
        <div className="wkRunCard">
          <div className="wkRunHead"><b>{tr("work.phong_review")}{e.round ? tr("work.vong", {p0: e.round}) : ""}</b><span className="wkBadge is-review">{e.turns} {tr("work.luot_noi")}</span>
            <span className="wkGrow"/><span className="ui-num">{money(e.cost_usd)}</span></div>
          <small>{e.speakers.map((s: any) => `${s.who?.name || "?"} ${money(s.cost_usd)}${s.error ? tr("work.loi_2") : ""}`).join(" · ")}</small>
        </div><time>{clock(e.at)}</time></li>;
      return <li key={i} className="wkEv is-run" data-testid="wk-run-card"><span className={"wkDot is-" + e.status}/>
        <div className="wkRunCard">
          <div className="wkRunHead"><b>{tr("work.luot")}{e.id}</b>
            <span className={"wkBadge is-" + (e.status === "failed" ? "failed" : e.status === "running" ? "running" : "")}>{e.status === "running" && <span className="ui-pulse"/>}{e.status_vi}</span>
            <span className="wkMuted">{e.trigger_vi}{e.who ? ` · ${e.who.name}` : ""}</span>
            <span className="wkGrow"/><span className="ui-num" data-testid="wk-run-cost">{money(e.cost_usd)}</span></div>
          <small className="wkMuted">{e.duration_s !== null ? dur(e.duration_s) : e.status === "running" ? tr("work.dang_chay_3") : ""}
            {e.tokens_in + e.tokens_out > 0 ? tr("work.vao_ra_token", {p0: e.tokens_in.toLocaleString(intlLocale()), p1: e.tokens_out.toLocaleString(intlLocale())}) : ""}</small>
          {e.error_vi && <p className="wkRunErr"><Icon name="alert" size={13}/>{e.error_vi}{e.error_reason && <details><summary>{tr("work.loi_goc")}</summary><pre>{e.error_reason}</pre></details>}</p>}
          {e.entries.map((x: any) => <div key={x.seq} className="wkRunEntry"><b>{x.kind_vi}:</b> {x.summary}
            {x.detail && <details><summary>{tr("work.chi_tiet")}</summary><pre>{x.detail}</pre></details>}</div>)}
        </div><time>{clock(e.at)}</time></li>;
    })}
  </ol>;
}

function ReviewTab({t, meta, busy, act}: {t: any; meta: any; busy: boolean; act: (fn: () => Promise<any>, ok?: string) => void}) {
  const r = t.review;
  const [pick, setPick] = useState<string>(""), [note, setNote] = useState("");
  const me = meta?.me;
  const mine = r.state === "in_review" && r.reviewer && r.reviewer.id === me;
  const cands = (meta?.members || []).filter((m: any) => m.assignable && m.id !== t.assignee?.id);
  return <div className="wkReview">
    <p className="wkMuted">{tr("work.review_cheo_viec_chi_duoc")} <b>{tr("work.khac_nguoi_lam")}</b> {tr("work.duyet_agent_review_trong_mot")}</p>
    {r.needed ? <div className="wkReviewState" data-testid="wk-review-state">
      <div><span className="wkLabel">{tr("work.nguoi_review")}</span>{r.reviewers.map((x: any) => <span key={x.id} className="ui-who"><Avatar who={x}/>{x.name}</span>)}</div>
      <div><span className="wkLabel">{tr("work.trang_thai")}</span><b>{r.state_vi || tr("work.chua_toi_luot_review")}</b>{r.round ? tr("work.vong", {p0: r.round}) : ""}</div>
      {r.missing_report && <p className="wkWarn">{tr("work.agent_lam_xong_nhung_khong")}</p>}
      {r.inconclusive_room_id && <p className="wkWarn">{tr("work.phong_review_2")}{r.inconclusive_room_id} {tr("work.chua_ra_quyet_dinh_chuyen")}</p>}
      {r.state === "in_review" && r.reviewer?.type === "agent" && <p className="wkMuted">{r.reviewer.name} {tr("work.agent_dang_review_ket_qua")}</p>}
    </div> : <p className="ui-empty-line">{tr("work.viec_nay_chua_co_review")}</p>}

    {mine && <div className="wkDecide" data-testid="wk-decide">
      <textarea value={note} onChange={e => setNote(e.target.value)} placeholder={tr("work.nhan_xet_bat_buoc_khi")} rows={3}/>
      <div className="ui-confirm-actions">
        <button className="ui-btn is-primary" disabled={busy} onClick={() => act(() => apiWork.decide(t.id, "approve", note), tr("work.da_duyet"))}>{tr("work.duyet")}</button>
        <button className="ui-btn is-ghost" disabled={busy || !note.trim()} onClick={() => act(() => apiWork.decide(t.id, "revise", note), tr("work.da_gui_yeu_cau_sua"))}>{tr("work.yeu_cau_sua")}</button>
      </div></div>}

    {meta?.caps?.set_reviewers && r.state !== "in_review" && <div className="wkPick">
      <select value={pick} onChange={e => setPick(e.target.value)} aria-label={tr("work.chon_nguoi_review")} data-testid="wk-reviewer-pick">
        <option value="">{tr("work.chon_nguoi_review_2")}</option>
        {cands.map((m: any) => <option key={m.id} value={m.id}>{m.name}{m.type === "agent" ? " (agent)" : ""}</option>)}</select>
      <button className="ui-btn is-ghost is-sm" disabled={busy || !pick} data-testid="wk-reviewer-set"
              onClick={() => act(() => apiWork.reviewers(t.id, [Number(pick)]), tr("work.da_dat_nguoi_review"))}>{tr("work.dat")}</button>
      {t.suggested_reviewer && <button className="ui-btn is-ghost is-sm" disabled={busy}
              onClick={() => act(() => apiWork.reviewers(t.id, [t.suggested_reviewer.id]), tr("work.da_dat_nguoi_review"))}>{tr("work.goi_y")} {t.suggested_reviewer.name}</button>}
      {r.needed && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => act(() => apiWork.reviewers(t.id, []), tr("work.da_bo_review"))}>{tr("work.bo_review")}</button>}
    </div>}

    {r.history?.length > 0 && <ol className="wkTimeline">{[...r.history].reverse().map((h: any, i: number) =>
      <li key={i} className="wkEv is-entry"><span className={"wkDot " + (h.decision === "approve" ? "is-completed" : "is-failed")}/>
        <div><b>{h.decision_vi}</b> · {h.reviewer?.name || "?"} {tr("work.vong_2")} {h.round}{h.via === "room" ? tr("work.phong_review_3") : ""}
          {h.note && <details><summary>{tr("work.nhan_xet")}</summary><pre>{h.note}</pre></details>}</div><time>{clock(h.at)}</time></li>)}</ol>}
  </div>;
}

function DescTab({t, busy, patch}: {t: any; busy: boolean; patch: (b: any) => void}) {
  const [d, setD] = useState(t.description), [a, setA] = useState(t.acceptance_criteria);
  useEffect(() => { setD(t.description); setA(t.acceptance_criteria); }, [t.id, t.description, t.acceptance_criteria]);
  const dirty = d !== t.description || a !== t.acceptance_criteria;
  return <div className="wkDesc">
    <label>{tr("work.mo_ta")}<textarea rows={6} value={d} onChange={e => setD(e.target.value)} placeholder={tr("work.agent_se_nhan_mo_ta")}/></label>
    <label>{tr("work.tieu_chi_nghiem_thu")}<textarea rows={3} value={a} onChange={e => setA(e.target.value)} placeholder={tr("work.reviewer_cham_theo_tieu_chi")}/></label>
    <button className="ui-btn is-primary is-sm" disabled={busy || !dirty} onClick={() => patch({description: d, acceptance_criteria: a})}>{tr("work.luu")}</button>
  </div>;
}

// ------------------------------------------------------------------ tạo việc

function CreateTask({meta, onClose, onCreated}: {meta: any; onClose: () => void; onCreated: (id: number) => void}) {
  const projects = (meta.projects || []) as any[], members = ((meta.members || []) as any[]).filter(m => m.assignable);
  const depts = (meta.departments || []) as any[];
  const [f, setF] = useState<any>({title: "", project_id: projects[0]?.id || "", to: "", reviewer: "", priority: "medium",
    due_at: "", description: "", acceptance_criteria: "", start: true});
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const set = (k: string, v: any) => setF((x: any) => ({...x, [k]: v}));
  const project = projects.find(p => String(p.id) === String(f.project_id));
  const assignee = f.to.startsWith("m:") ? members.find(m => `m:${m.id}` === f.to) : null;
  // gợi ý review chéo: trưởng phòng của người nhận (nếu không phải chính họ)
  const suggestion = useMemo(() => {
    if (!assignee) return null;
    const d = depts.find(x => x.id === assignee.department_id);
    const head = d && d.head_member_id !== assignee.id ? members.find(m => m.id === d.head_member_id) : null;
    return head || null;
  }, [assignee, depts, members]);
  useEffect(() => { if (meta.caps?.set_reviewers && suggestion && !f.reviewer) set("reviewer", String(suggestion.id)); // eslint-disable-next-line
  }, [suggestion]);
  useEffect(() => { const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc); return () => window.removeEventListener("keydown", esc); }, [onClose]);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr("");
    if (!f.title.trim()) { setErr(tr("work.can_dat_ten_cho_viec")); return; }
    if (!f.project_id) { setErr(tr("work.chon_du_an_cho_viec")); return; }
    setBusy(true);
    try {
      const body: any = {title: f.title.trim(), project_id: Number(f.project_id), priority: f.priority, description: f.description,
        acceptance_criteria: f.acceptance_criteria, due_at: f.due_at || null, start: f.start,
        reviewer_member_ids: f.reviewer && meta.caps?.set_reviewers ? [Number(f.reviewer)] : []};
      if (f.to.startsWith("m:")) body.assignee_member_id = Number(f.to.slice(2));
      if (f.to.startsWith("d:")) body.department_id = Number(f.to.slice(2));
      const t = await apiWork.create(body);
      onCreated(t.id);
    } catch (e2) { setErr(errorText(e2)); } finally { setBusy(false); }
  }
  if (!projects.length) return <div className="wkModalWrap"><div className="wkModal" role="dialog" aria-label={tr("work.tao_viec")}>
    <h2>{tr("work.chua_co_du_an")}</h2><p>{tr("work.viec_phai_nam_trong_mot")} <Link href="/app/os?tab=projects">{tr("work.du_an")}</Link>.</p>
    <button className="ui-btn is-ghost" onClick={onClose}>{tr("work.dong")}</button></div></div>;
  return <div className="wkModalWrap" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="wkModal" role="dialog" aria-label={tr("work.tao_viec")} onSubmit={submit} data-testid="wk-create">
      <h2>{tr("work.tao_viec")}</h2>
      <input autoFocus className="wkTitleEdit" value={f.title} onChange={e => set("title", e.target.value)} placeholder={tr("work.ten_viec_vi_du_viet")} data-testid="wk-create-title"/>
      <div className="wkProps">
        <label>{tr("work.du_an")}<select value={f.project_id} onChange={e => set("project_id", e.target.value)} data-testid="wk-create-project">
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Giao cho<select value={f.to} onChange={e => { set("to", e.target.value); set("reviewer", ""); }} data-testid="wk-create-to">
          <option value="">{tr("work.chua_giao")}</option>
          <optgroup label="Agent">{members.filter(m => m.type === "agent" && (!project || !m.company_id || m.company_id === project.company_id))
            .map(m => <option key={m.id} value={`m:${m.id}`}>{m.name}{m.role ? ` — ${m.role}` : ""}</option>)}</optgroup>
          <optgroup label={tr("work.nguoi")}>{members.filter(m => m.type !== "agent").map(m => <option key={m.id} value={`m:${m.id}`}>{m.name}</option>)}</optgroup>
          {depts.length > 0 && <optgroup label={tr("work.giao_cho_phong_truong_phong")}>{depts.filter(d => !project || d.company_id === project.company_id)
            .map(d => <option key={d.id} value={`d:${d.id}`}>{tr("work.phong")} {d.name}</option>)}</optgroup>}
        </select></label>
        <label>{tr("work.uu_tien_2")}<select value={f.priority} onChange={e => set("priority", e.target.value)}>
          {(meta.priorities || []).map((p: any) => <option key={p.key} value={p.key}>{prioLabel(p)}</option>)}</select></label>
        <label>{tr("work.han_chot")}<input type="date" value={f.due_at} onChange={e => set("due_at", e.target.value)}/></label>
      </div>
      {meta.caps?.set_reviewers && <label className="wkWide">{tr("work.review_cheo_nguoi_duyet_truoc")}
        <select value={f.reviewer} onChange={e => set("reviewer", e.target.value)} data-testid="wk-create-reviewer">
          <option value="">{tr("work.khong_can_review")}</option>
          {members.filter(m => !assignee || m.id !== assignee.id).map(m =>
            <option key={m.id} value={m.id}>{m.name}{m.type === "agent" ? " (agent)" : ""}{suggestion?.id === m.id ? tr("work.truong_phong_goi_y") : ""}</option>)}
        </select></label>}
      <label className="wkWide">{tr("work.mo_ta")}<textarea rows={4} value={f.description} onChange={e => set("description", e.target.value)} placeholder={tr("work.boi_canh_dau_vao_ket")}/></label>
      <label className="wkWide">{tr("work.tieu_chi_nghiem_thu")}<textarea rows={2} value={f.acceptance_criteria} onChange={e => set("acceptance_criteria", e.target.value)} placeholder={tr("work.reviewer_cham_theo_tieu_chi")}/></label>
      <label className="wkCheck"><input type="checkbox" checked={f.start} onChange={e => set("start", e.target.checked)}/>
        {tr("work.bat_dau_ngay")} {assignee?.type === "agent" ? tr("work.nhan_viec_luon", {p0: assignee.name}) : tr("work.chuyen_sang_can_lam")}</label>
      {err && <p className="ui-inline-error" role="alert">{err}</p>}
      <div className="ui-confirm-actions">
        <button className="ui-btn is-primary" disabled={busy} data-testid="wk-create-submit">{busy ? tr("work.dang_tao") : tr("work.tao_viec")}</button>
        <button type="button" className="ui-btn is-ghost" onClick={onClose}>{tr("work.huy")}</button>
      </div>
    </form>
  </div>;
}
