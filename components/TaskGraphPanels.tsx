"use client";
import {useEffect, useState} from "react";
import Link from "next/link";
import {api, apiTask, apiV9, errorText} from "../lib/api";
import {t as tr, lazy, intlLocale} from "../lib/i18n";
import {ErrorBanner} from "./ui/EmptyState";

/* D1.3 + D1.4 — hai panel của màn hình chi tiết công việc.

   * **Liên kết**: việc này phục vụ mục tiêu nào, nằm dưới việc nào, và đang
     chờ việc nào. Dòng "chuỗi mục tiêu" là đúng dòng agent nhận ở khối 2 của
     gói ngữ cảnh — lấy từ cùng hàm `task_graph.goal_line`.
   * **Lượt chạy**: mỗi lần agent nhận việc là một hàng `task_runs`. Trước D1.4
     chỉ có `runtime_run_id` của lượt cuối, nên không ai biết việc đã chạy mấy
     lần và lần nào hỏng vì sao. */

type Row = Record<string, any>;

const STATUS_VI: Record<string, string> = lazy(() => ({
  backlog: tr("taskGraph.ton_dong"), todo: tr("taskGraph.can_lam"), in_progress: tr("taskGraph.dang_lam"), review: tr("taskGraph.cho_duyet"),
  blocked: tr("taskGraph.bi_chan"), done: "xong", cancelled: tr("taskGraph.da_huy"),
}));
const RUN_VI: Record<string, {text: string; cls: string}> = lazy(() => ({
  queued: {text: tr("taskGraph.cho_chay"), cls: "mid"}, dispatched: {text: tr("taskGraph.da_giao"), cls: "mid"},
  running: {text: tr("taskGraph.dang_chay"), cls: "mid"}, completed: {text: "xong", cls: "low"},
  failed: {text: tr("taskGraph.hong"), cls: "high"}, cancelled: {text: tr("taskGraph.da_huy"), cls: "mid"},
  skipped: {text: tr("taskGraph.bo_qua"), cls: "mid"},
}));

function when(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(intlLocale(),
    {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
}

function TaskChip({t, onRemove}: {t: Row; onRemove?: () => void}) {
  const closed = t.status === "done" || t.status === "cancelled";
  return <span style={{display: "inline-flex", gap: 6, alignItems: "center",
                       border: "1px solid var(--border)", borderRadius: 999,
                       padding: "3px 4px 3px 10px", fontSize: 12.5, margin: "0 6px 6px 0",
                       opacity: closed ? .7 : 1}}>
    <Link href={`/app/tasks/${t.id}`}>#{t.id} {t.title}</Link>
    <small style={{color: closed ? "var(--text-muted)" : "var(--accent)"}}>
      {STATUS_VI[t.status] || t.status}</small>
    {onRemove && <button aria-label={tr("taskGraph.go", {p0: t.id})} onClick={onRemove}
      style={{border: "none", background: "none", padding: "0 6px", fontSize: 14,
              color: "var(--text-muted)", cursor: "pointer"}}>×</button>}
  </span>;
}

export function TaskLinksPanel({taskId, onChange}: {taskId: number; onChange?: () => void}) {
  const [graph, setGraph] = useState<Row | null>(null);
  const [tasks, setTasks] = useState<Row[]>([]);
  const [goals, setGoals] = useState<Row[]>([]);
  const [blocker, setBlocker] = useState("");
  const [criteria, setCriteria] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const g = await apiTask.graph(taskId);
      setGraph(g); setCriteria(g.acceptance_criteria || "");
    } catch (e) { setError(errorText(e, tr("taskGraph.khong_tai_duoc_lien_ket"))); }
    try {
      const rows = await api.tasks() as Row[];
      setTasks((rows || []).filter(t => t.id !== taskId));
    } catch { /* danh sách chọn chỉ là tiện ích */ }
    try { setGoals((await apiV9.goals() as Row[]) || []); } catch {}
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [taskId]);

  async function act(fn: () => Promise<any>) {
    setBusy(true); setError("");
    try { const out = await fn(); setGraph(out.graph || out); onChange?.(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  if (!graph) return <div className="ui-panel"><div className="ui-empty-line">
    {error || tr("taskGraph.dang_tai_lien_ket")}</div></div>;

  const linked = new Set<number>([taskId, ...graph.blocked_by.map((t: Row) => t.id)]);
  const parentId = graph.parents[0]?.id;
  const ownGoal = graph.goal && !graph.goal.inherited ? graph.goal.id : null;

  return <div className="ui-panel" data-testid="task-links">
    <div className="ui-panel-head">
      <div><b>{tr("taskGraph.lien_ket")}</b></div>
      <small>{tr("taskGraph.muc_tieu_cha_con_phu")}</small>
    </div>

    <div style={{fontSize: 12.5, color: "var(--text-muted)"}}>{tr("taskGraph.chuoi_muc_tieu_agent_nhan")}</div>
    <div data-testid="goal-line" style={{fontSize: 13.5, margin: "4px 0 12px", lineHeight: 1.5}}>
      {graph.goal_line}
    </div>

    {!!graph.open_blocker_ids.length && <div className="ui-banner is-error" style={{marginBottom: 10}}>
      {tr("taskGraph.con_bi_chan_boi")} {graph.open_blocker_ids.map((i: number) => `#${i}`).join(", ")}{tr("taskGraph.chua_chuyen_sang_dang_lam")}
    </div>}

    <label style={{fontSize: 12.5, fontWeight: 600}}>{tr("taskGraph.muc_tieu")}</label>
    <select value={ownGoal ?? ""} disabled={busy}
            onChange={e => act(() => apiTask.setLinks(taskId,
              {goal_id: e.target.value ? Number(e.target.value) : null}))}
            style={{width: "100%", padding: 8, borderRadius: 9, margin: "4px 0 4px",
                    border: "1px solid var(--border)"}}>
      <option value="">{graph.goal?.inherited ? tr("taskGraph.ke_thua", {p0: graph.goal.title})
                                              : tr("taskGraph.chua_gan_muc_tieu")}</option>
      {goals.map(g => <option key={g.id} value={g.id}>{g.title}</option>)}
    </select>

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 10}}>{tr("taskGraph.viec_cha")}</label>
    <select value={parentId ?? ""} disabled={busy}
            onChange={e => act(() => apiTask.setLinks(taskId,
              {parent_task_id: e.target.value ? Number(e.target.value) : null}))}
            style={{width: "100%", padding: 8, borderRadius: 9, marginTop: 4,
                    border: "1px solid var(--border)"}}>
      <option value="">{tr("taskGraph.khong_co")}</option>
      {tasks.map(t => <option key={t.id} value={t.id}>#{t.id} {t.title}</option>)}
    </select>

    {!!graph.children.length && <>
      <div style={{fontSize: 12.5, fontWeight: 600, marginTop: 10}}>{tr("taskGraph.viec_con")}</div>
      <div style={{marginTop: 4}}>{graph.children.map((t: Row) => <TaskChip key={t.id} t={t}/>)}</div>
    </>}

    <div style={{fontSize: 12.5, fontWeight: 600, marginTop: 12}}>{tr("taskGraph.dang_cho_viec")}</div>
    <div style={{marginTop: 4}}>
      {graph.blocked_by.length
        ? graph.blocked_by.map((t: Row) =>
            <TaskChip key={t.id} t={t}
                      onRemove={() => act(() => apiTask.removeBlocker(taskId, t.id))}/>)
        : <small style={{color: "var(--text-muted)"}}>{tr("taskGraph.khong_cho_viec_nao")}</small>}
    </div>
    <div style={{display: "flex", gap: 6, marginTop: 4}}>
      <select value={blocker} onChange={e => setBlocker(e.target.value)} disabled={busy}
              aria-label={tr("taskGraph.chon_viec_phai_xong_truoc")}
              style={{flex: 1, padding: 8, borderRadius: 9, border: "1px solid var(--border)"}}>
        <option value="">{tr("taskGraph.them_viec_phai_xong_truoc")}</option>
        {tasks.filter(t => !linked.has(t.id)).map(t =>
          <option key={t.id} value={t.id}>#{t.id} {t.title}</option>)}
      </select>
      <button disabled={busy || !blocker}
              onClick={() => act(async () => {
                const out = await apiTask.addBlocker(taskId, Number(blocker));
                setBlocker(""); return out;
              })}>{tr("taskGraph.them")}</button>
    </div>

    {!!graph.blocking.length && <>
      <div style={{fontSize: 12.5, fontWeight: 600, marginTop: 12}}>{tr("taskGraph.dang_chan")}</div>
      <div style={{marginTop: 4}}>{graph.blocking.map((t: Row) => <TaskChip key={t.id} t={t}/>)}</div>
    </>}

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 12}}>
      {tr("taskGraph.tieu_chi_nghiem_thu")}
    </label>
    <textarea value={criteria} onChange={e => setCriteria(e.target.value)} rows={3}
              placeholder={tr("taskGraph.the_nao_thi_coi_la")}
              style={{width: "100%", padding: 9, borderRadius: 9, marginTop: 4,
                      border: "1px solid var(--border)", fontSize: 13}}/>
    <button disabled={busy || criteria === (graph.acceptance_criteria || "")}
            onClick={() => act(() => apiTask.setLinks(taskId, {acceptance_criteria: criteria}))}
            style={{marginTop: 6}}>{tr("taskGraph.luu_tieu_chi")}</button>

    {error && <ErrorBanner error={error}/>}
  </div>;
}

export function TaskRunsPanel({taskId, refreshKey = 0}: {taskId: number; refreshKey?: number}) {
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    apiTask.runs(taskId).then(setData).catch(e => setError(errorText(e)));
  }, [taskId, refreshKey]);

  const runs: Row[] = data?.runs || [];
  return <div className="ui-panel" data-testid="task-runs">
    <div className="ui-panel-head">
      <div><b>{tr("taskGraph.luot_chay")}</b></div>
      <small>task_runs · {runs.length}</small>
    </div>
    {error && <ErrorBanner error={error}/>}
    {!error && !runs.length && <div className="ui-empty-line">
      {tr("taskGraph.chua_co_luot_chay_nao")}
    </div>}
    <div style={{display: "grid", gap: 8}}>
      {runs.map(r => {
        const s = RUN_VI[r.status] || {text: r.status, cls: "mid"};
        return <div key={r.id} style={{border: "1px solid var(--border)", borderRadius: 10,
                                       padding: "8px 10px", fontSize: 12.5}}>
          <div style={{display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap"}}>
            <b>{tr("taskGraph.luot")}{r.id}</b>
            <span className={`ui-pill ${s.cls}`}>{s.text}</span>
            {r.holds_task && <small style={{color: "var(--accent)"}}>{tr("taskGraph.dang_giu_viec")}</small>}
            <small style={{color: "var(--text-muted)", marginLeft: "auto"}}>
              {r.member_name || "—"} · {r.trigger_kind}
            </small>
          </div>
          <div style={{color: "var(--text-muted)", marginTop: 3}}>
            {tr("taskGraph.bat_dau")} {when(r.started_at || r.created_at)} {tr("taskGraph.ket_thuc")} {when(r.ended_at)}
            {r.cost_usd ? ` · $${Number(r.cost_usd).toFixed(4)}` : ""}
          </div>
          {r.error_reason && <div style={{marginTop: 3}}>{tr("taskGraph.ly_do")} {r.error_reason}</div>}
        </div>;
      })}
    </div>
  </div>;
}

/* Trang Mục tiêu: những việc gắn trực tiếp vào một mục tiêu. */
export function GoalTasks({goalId}: {goalId: number}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  // M1: không bao giờ gọi /tasks?goal_id=undefined (422 trong log khi mục tiêu chưa có id).
  useEffect(() => { if (!Number.isFinite(goalId)) { setRows([]); return; }
                    setRows(null); apiTask.byGoal(goalId).then(setRows).catch(() => setRows([])); },
            [goalId]);
  if (rows === null) return <div className="ui-empty-line">{tr("taskGraph.dang_tai_viec")}</div>;
  if (!rows.length) return <div className="ui-empty-line">
    {tr("taskGraph.chua_co_viec_nao_gan")}
  </div>;
  return <div className="ui-list">{rows.map(t =>
    <div className="ui-row" key={t.id}>
      <div><b><Link href={`/app/tasks/${t.id}`}>#{t.id} {t.title}</Link></b>
        <small>{STATUS_VI[t.status] || t.status} {tr("taskGraph.uu_tien")} {t.priority}</small></div>
    </div>)}</div>;
}


/* D2.1 — vì sao seat được (hoặc không được) đánh thức cho việc này. */
const WAKE_REASON_VI: Record<string, string> = lazy(() => ({
  assigned: tr("taskGraph.duoc_giao_viec"), mentioned: tr("taskGraph.duoc_nhac_ten"), handoff: tr("taskGraph.nhan_ban_giao"),
  approval_resolved: tr("taskGraph.approval_co_ket_qua"), blocker_cleared: tr("taskGraph.het_bi_chan"),
  review_requested: tr("taskGraph.duoc_nho_review"), routine: tr("taskGraph.lich_dinh_ky"), goal_created: tr("taskGraph.muc_tieu_moi"),
}));
const WAKE_STATUS_VI: Record<string, {text: string; cls: string}> = lazy(() => ({
  queued: {text: tr("taskGraph.dang_cho_gop"), cls: "mid"}, dispatched: {text: tr("taskGraph.da_chay"), cls: "low"},
  coalesced: {text: tr("taskGraph.gop_vao_luot_khac"), cls: "low"}, skipped: {text: tr("taskGraph.bo_qua"), cls: "high"},
  failed: {text: tr("taskGraph.loi"), cls: "high"},
}));

// Mã lý do giữ nguyên (để tra log/API), chỉ thêm câu tiếng Việt đứng trước.
const SKIP_VI: [string, string][] = lazy(() => ([
  ["seat_busy", tr("taskGraph.seat_dang_ban_mot_luot")],
  ["budget", tr("taskGraph.het_ngan_sach")], ["outside_active_hours", tr("taskGraph.ngoai_gio_lam_cua_agent")],
  ["seat_inactive", tr("taskGraph.seat_dang_tat")], ["not_an_agent_seat", tr("taskGraph.seat_khong_phai_agent")],
  ["not_assignee", tr("taskGraph.nguoi_duoc_nhac_khong_phai")],
  ["task_status", tr("taskGraph.viec_khong_o_trang_thai")], ["dispatch_error", tr("taskGraph.khong_gui_duoc_cho_agent")],
  ["runtime_error", tr("taskGraph.gateway_loi")],
]));
function skipText(code: string): string {
  const hit = SKIP_VI.find(([k]) => code.startsWith(k));
  return hit ? `${hit[1]} (${code})` : code;
}

export function TaskWakeupsPanel({taskId, refreshKey = 0}: {taskId: number; refreshKey?: number}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    apiTask.wakeups(taskId).then(setRows).catch(e => setError(errorText(e)));
  }, [taskId, refreshKey, tick]);
  // Còn dòng "đang chờ gộp" thì hỏi lại sau 4 giây: drain chạy ở backend, panel
  // không tự biết khi nào nó xử lý xong. Hết dòng chờ thì thôi hỏi.
  const pending = (rows || []).some(w => w.status === "queued");
  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => setTick(x => x + 1), 4000);
    return () => clearTimeout(t);
  }, [pending, tick]);
  const list = rows || [];
  return <div className="ui-panel" data-testid="task-wakeups">
    <div className="ui-panel-head">
      <div><b>{tr("taskGraph.danh_thuc")}</b></div>
      <small>wakeups · {list.length}</small>
    </div>
    {error && <ErrorBanner error={error}/>}
    {!error && rows && !list.length && <div className="ui-empty-line">
      {tr("taskGraph.chua_co_ly_do_nao")}
    </div>}
    <div style={{display: "grid", gap: 8}}>
      {list.map(w => {
        const s = WAKE_STATUS_VI[w.status] || {text: w.status, cls: "mid"};
        return <div key={w.id} data-testid="wakeup-row"
                    style={{border: "1px solid var(--border)", borderRadius: 10, padding: "8px 10px", fontSize: 12.5}}>
          <div style={{display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap"}}>
            <b>{WAKE_REASON_VI[w.reason] || w.reason}</b>
            <span className={`ui-pill ${s.cls}`}>{s.text}</span>
            <small style={{color: "var(--text-muted)", marginLeft: "auto"}}>
              {when(w.created_at)}{w.run_id ? tr("taskGraph.luot_2", {p0: w.run_id}) : ""}
            </small>
          </div>
          {w.skip_reason && <div style={{marginTop: 3}}>{tr("taskGraph.ly_do")} {skipText(w.skip_reason)}</div>}
          {w.coalesced_into_id && <div style={{marginTop: 3, color: "var(--text-muted)"}}>
            {tr("taskGraph.gop_cung_luot_voi_ly")}{w.coalesced_into_id} {tr("taskGraph.trong_cua_so_10_giay")}
          </div>}
        </div>;
      })}
    </div>
  </div>;
}
