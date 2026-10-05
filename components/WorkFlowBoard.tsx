"use client";
import Link from "next/link";
import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {Icon} from "./Icon";
import {apiV17, apiV18, apiV27} from "../lib/api";
import {refreshCounts} from "../lib/counts";

/* Bảng việc v6.

   Sửa ba lỗi của bản v5: (1) cột "spec_ready" không tồn tại trong backend —
   trạng thái thật là backlog/todo/in_progress/review/blocked/done
   (board_truth.py); (2) đọc /tasks nên không có tên người làm, mọi thẻ hiện
   "Chưa giao" — giờ đọc /v17/workspace/tasks có assignee_name/assignee_type;
   (3) hiện "thời gian trong trạng thái" nhưng backend không trả mốc thời gian
   nào, nên con số đó là bịa — bỏ.

   Chuyển trạng thái đi qua /v27/tasks/{id}/move (có kiểm revision, trả lại
   project_truth). Kéo thả cho chuột, menu "Chuyển sang" cho bàn phím. */

type Task = {
  id: number; title: string; status: string; priority?: string;
  project_id?: number; project_name?: string; company_name?: string;
  assignee_member_id?: number | null; assignee_name?: string | null; assignee_type?: "agent" | "human" | null;
  runtime_run_id?: string | number | null;
};

export const STATUSES: {key: string; label: string}[] = [
  {key: "backlog", label: "Tồn đọng"},
  {key: "todo", label: "Cần làm"},
  {key: "in_progress", label: "Đang làm"},
  {key: "review", label: "Chờ duyệt"},
  {key: "blocked", label: "Bị chặn"},
  {key: "done", label: "Xong"},
];
const PRIORITY: Record<string, {label: string; rank: number}> = {
  urgent: {label: "Khẩn", rank: 0}, high: {label: "Cao", rank: 1}, medium: {label: "Vừa", rank: 2}, low: {label: "Thấp", rank: 3},
};

type Scope = "all" | "agent" | "human";
type Chip = "running" | "high" | "unassigned";

function Who({t}: {t: Task}) {
  if (!t.assignee_name) return <span className="ui-who is-none"><span className="ui-ava is-none">?</span>Chưa giao</span>;
  return <span className="ui-who">
    <span className={"ui-ava " + (t.assignee_type === "agent" ? "is-agent" : "is-human")} aria-hidden="true">
      {t.assignee_type === "agent" ? <Icon name="sparkle" size={11} strokeWidth={2}/> : t.assignee_name.slice(0, 1).toUpperCase()}
    </span>
    {t.assignee_name}
  </span>;
}

/* Menu dùng position:fixed theo toạ độ nút, vì cột board có overflow-x để
   cuộn ngang — một menu absolute bên trong sẽ bị cắt mất. */
function MoveMenu({t, anchor, onMove, onClose}: {t: Task; anchor: DOMRect; onMove: (s: string) => void; onClose: () => void}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
    const out = (e: MouseEvent) => { if (!ref.current?.parentElement?.contains(e.target as Node)) onClose(); };
    const scroll = () => onClose();
    document.addEventListener("mousedown", out);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", scroll);
    return () => {
      document.removeEventListener("mousedown", out);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", scroll);
    };
  }, [onClose]);
  const W = 200, H = 260;
  const left = Math.max(8, Math.min(anchor.right - W, window.innerWidth - W - 8));
  const top = anchor.bottom + 4 + H > window.innerHeight ? Math.max(8, anchor.top - H - 4) : anchor.bottom + 4;
  const onKey = (e: React.KeyboardEvent) => {
    const items = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") || []);
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") {
      e.preventDefault();
      ref.current?.parentElement?.querySelector<HTMLButtonElement>("button")?.focus();
      onClose();
    }
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
  };
  return <div className="ui-pop ui-move" role="menu" ref={ref} onKeyDown={onKey}
              style={{position: "fixed", top, left, insetInlineEnd: "auto", width: W}}>
    <p className="ui-pop-label">Chuyển sang</p>
    {STATUSES.map(s => <button key={s.key} role="menuitem" disabled={s.key === t.status} onClick={() => onMove(s.key)}>
      <span className={"ui-sdot is-" + s.key}/>{s.label}{s.key === t.status && <small>hiện tại</small>}
    </button>)}
  </div>;
}

function Card({t, onMove, dragging, setDragging}: {
  t: Task; onMove: (t: Task, s: string) => void; dragging: number | null; setDragging: (id: number | null) => void;
}) {
  const [menu, setMenu] = useState<DOMRect | null>(null);
  const pr = t.priority ? PRIORITY[t.priority] : undefined;
  return <article className={"ui-card" + (dragging === t.id ? " is-dragging" : "")} draggable
                  onDragStart={e => { e.dataTransfer.setData("text/plain", String(t.id)); e.dataTransfer.effectAllowed = "move"; setDragging(t.id); }}
                  onDragEnd={() => setDragging(null)}>
    <div className="ui-card-top">
      <Link href={`/app/tasks/${t.id}`} className="ui-card-title" draggable={false}>{t.title}</Link>
      <div className="ui-card-menu">
        <button className="ui-iconbtn is-sm" aria-label={`Chuyển trạng thái: ${t.title}`} aria-haspopup="menu" aria-expanded={!!menu}
                onClick={e => { const r = e.currentTarget.getBoundingClientRect(); setMenu(m => m ? null : r); }}><Icon name="more" size={16} strokeWidth={2.4}/></button>
        {menu && <MoveMenu t={t} anchor={menu} onClose={() => setMenu(null)} onMove={s => { setMenu(null); onMove(t, s); }}/>}
      </div>
    </div>
    <p className="ui-card-meta">
      <span className="ui-mono">#{t.id}</span>
      {t.project_name && <><span>·</span><span className="ui-ellipsis">{t.project_name}</span></>}
    </p>
    <div className="ui-card-foot">
      <Who t={t}/>
      {t.runtime_run_id ? <span className="ui-status is-running"><span className="ui-pulse"/>Đang chạy</span> : null}
      {pr && pr.rank <= 1 && <span className={"ui-prio is-" + t.priority}>{pr.label}</span>}
    </div>
  </article>;
}

function QuickAdd({status, projectId, onAdded}: {status: string; projectId?: number; onAdded: () => void}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!projectId) return null;
  if (!open) return <button className="ui-col-add" onClick={() => setOpen(true)}><Icon name="plus" size={14}/>Thêm nhiệm vụ</button>;
  const submit = async () => {
    if (!title.trim()) { setOpen(false); return; }
    setBusy(true); setErr(null);
    try {
      const created: any = await apiV18.createTask({project_id: projectId, title: title.trim(), priority: "medium"});
      if (status !== "backlog" && created?.id) await apiV27.moveTask(created.id, status);
      setTitle(""); setOpen(false); onAdded();
    } catch { setErr("Không tạo được nhiệm vụ."); }
    finally { setBusy(false); }
  };
  return <form className="ui-quickadd" onSubmit={e => { e.preventDefault(); submit(); }}>
    <input autoFocus value={title} onChange={e => setTitle(e.target.value)} disabled={busy}
           placeholder="Tên nhiệm vụ…" aria-label="Tên nhiệm vụ mới"
           onKeyDown={e => { if (e.key === "Escape") { setOpen(false); setTitle(""); } }}/>
    {err && <p className="ui-inline-error">{err}</p>}
    <div className="ui-confirm-actions">
      <button className="ui-btn is-primary is-sm" disabled={busy}>{busy ? "Đang tạo…" : "Tạo"}</button>
      <button type="button" className="ui-btn is-ghost is-sm" onClick={() => { setOpen(false); setTitle(""); }}>Huỷ</button>
    </div>
  </form>;
}

export function WorkFlowBoard() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope>("all");
  const [chips, setChips] = useState<Chip[]>([]);
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const load = useCallback(() => {
    apiV17.tasks()
      .then(rows => { setTasks(Array.isArray(rows) ? rows : []); setError(null); })
      .catch(() => setError("Không tải được nhiệm vụ. Kiểm tra backend rồi thử lại."));
  }, []);
  useEffect(load, [load]);

  const move = async (t: Task, status: string) => {
    if (t.status === status) return;
    const before = tasks;
    setMoveError(null);
    setTasks(ts => ts?.map(x => x.id === t.id ? {...x, status} : x) || ts);
    try { await apiV27.moveTask(t.id, status); refreshCounts(); }
    catch (e: any) {
      setTasks(before);
      const label = STATUSES.find(s => s.key === status)?.label;
      setMoveError(`Không chuyển được “${t.title}” sang ${label}. ${String(e?.message || "").includes("409") ? "Nhiệm vụ vừa được người khác sửa — tải lại để xem bản mới." : "Thử lại."}`);
    }
  };

  const rows = tasks || [];
  const inScope = useMemo(() => rows.filter(t => {
    if (scope !== "all" && t.assignee_type !== scope) return false;
    if (chips.includes("running") && !t.runtime_run_id) return false;
    if (chips.includes("high") && !(t.priority === "urgent" || t.priority === "high")) return false;
    if (chips.includes("unassigned") && t.assignee_name) return false;
    return true;
  }), [rows, scope, chips]);

  const count = (pred: (t: Task) => boolean) => rows.filter(pred).length;
  const toggle = (c: Chip) => setChips(cs => cs.includes(c) ? cs.filter(x => x !== c) : [...cs, c]);
  const defaultProject = rows.find(t => t.project_id)?.project_id;

  if (error) return <div className="ui-banner is-error" role="alert"><Icon name="alert" size={16}/><span>{error}</span>
    <button className="ui-btn is-ghost" onClick={load}>Tải lại</button></div>;
  if (!tasks) return <div className="ui-board" aria-busy="true">{STATUSES.map(s =>
    <div key={s.key} className="ui-col"><div className="ui-skel" style={{height: 18, width: 90}}/><div className="ui-skel" style={{height: 84}}/></div>)}</div>;

  return <div className="ui-stack is-tight">
    <div className="ui-statline" aria-label="Tóm tắt">
      <span><b className="ui-num">{count(t => t.status === "in_progress")}</b> đang làm</span>
      <span className={count(t => t.status === "blocked") ? "is-blocked" : ""}><b className="ui-num">{count(t => t.status === "blocked")}</b> bị chặn</span>
      <span><b className="ui-num">{count(t => t.status === "review")}</b> chờ duyệt</span>
      <span><b className="ui-num">{count(t => t.status === "done")}</b>/<span className="ui-num">{rows.length}</span> xong</span>
      {count(t => t.status === "blocked" || t.status === "review") > 0 &&
        <Link href="/app/inbox" className="ui-link">Xử lý trong Hộp việc<Icon name="arrow-right" size={13}/></Link>}
    </div>

    <div className="ui-toolbar">
      <div className="ui-seg" role="group" aria-label="Người làm">
        {([["all", "Tất cả"], ["agent", "Agent làm"], ["human", "Người làm"]] as [Scope, string][]).map(([k, l]) =>
          <button key={k} aria-pressed={scope === k} onClick={() => setScope(k)}>{l}</button>)}
      </div>
      <div className="ui-chips">
        {([["running", "Đang chạy runtime"], ["high", "Ưu tiên cao"], ["unassigned", "Chưa giao"]] as [Chip, string][]).map(([k, l]) =>
          <button key={k} className="ui-chip" aria-pressed={chips.includes(k)} onClick={() => toggle(k)}>{l}</button>)}
      </div>
      <span className="ui-toolbar-count">{inScope.length === rows.length ? `${rows.length} nhiệm vụ` : `${inScope.length} / ${rows.length} nhiệm vụ`}</span>
    </div>

    {moveError && <div className="ui-banner is-error" role="alert"><Icon name="alert" size={16}/><span>{moveError}</span>
      <button className="ui-btn is-ghost" onClick={() => { setMoveError(null); load(); }}>Tải lại</button></div>}

    {rows.length === 0 ? <div className="ui-empty">
      <Icon name="board" size={20}/><b>Chưa có nhiệm vụ nào</b>
      <span>Đưa một mục tiêu cho Nina để chia việc, hoặc tạo nhiệm vụ trong Vận hành tổ chức.</span>
      <Link href="/app/nina" className="ui-btn is-primary">Mở Nina lập kế hoạch</Link>
    </div> :
    <div className="ui-board">
      {STATUSES.map(s => {
        const items = inScope.filter(t => t.status === s.key)
          .sort((a, b) => (PRIORITY[a.priority || ""]?.rank ?? 9) - (PRIORITY[b.priority || ""]?.rank ?? 9));
        return <section key={s.key} className={"ui-col" + (over === s.key ? " is-over" : "") + (items.length === 0 ? " is-empty" : "")}
                        aria-label={`${s.label}, ${items.length} nhiệm vụ`}
                        onDragOver={e => { if (dragging !== null) { e.preventDefault(); setOver(s.key); } }}
                        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(null); }}
                        onDrop={e => {
                          e.preventDefault(); setOver(null);
                          const id = Number(e.dataTransfer.getData("text/plain"));
                          const t = rows.find(x => x.id === id); if (t) move(t, s.key);
                        }}>
          <header className="ui-col-head">
            <span className={"ui-sdot is-" + s.key}/>
            <h2>{s.label}</h2>
            <span className="ui-num">{items.length}</span>
          </header>
          <div className="ui-col-body">
            {items.map(t => <Card key={t.id} t={t} onMove={move} dragging={dragging} setDragging={setDragging}/>)}
            {items.length === 0 && <p className="ui-col-empty">Trống</p>}
          </div>
          <QuickAdd status={s.key} projectId={defaultProject} onAdded={load}/>
        </section>;
      })}
    </div>}
  </div>;
}
