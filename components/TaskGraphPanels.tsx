"use client";
import {useEffect, useState} from "react";
import Link from "next/link";
import {api, apiTask, apiV9, errorText} from "../lib/api";

/* D1.3 + D1.4 — hai panel của màn hình chi tiết công việc.

   * **Liên kết**: việc này phục vụ mục tiêu nào, nằm dưới việc nào, và đang
     chờ việc nào. Dòng "chuỗi mục tiêu" là đúng dòng agent nhận ở khối 2 của
     gói ngữ cảnh — lấy từ cùng hàm `task_graph.goal_line`.
   * **Lượt chạy**: mỗi lần agent nhận việc là một hàng `task_runs`. Trước D1.4
     chỉ có `runtime_run_id` của lượt cuối, nên không ai biết việc đã chạy mấy
     lần và lần nào hỏng vì sao. */

type Row = Record<string, any>;

const STATUS_VI: Record<string, string> = {
  backlog: "tồn đọng", todo: "cần làm", in_progress: "đang làm", review: "chờ duyệt",
  blocked: "bị chặn", done: "xong", cancelled: "đã huỷ",
};
const RUN_VI: Record<string, {text: string; cls: string}> = {
  queued: {text: "chờ chạy", cls: "mid"}, dispatched: {text: "đã giao", cls: "mid"},
  running: {text: "đang chạy", cls: "mid"}, completed: {text: "xong", cls: "low"},
  failed: {text: "hỏng", cls: "high"}, cancelled: {text: "đã huỷ", cls: "mid"},
  skipped: {text: "bỏ qua", cls: "mid"},
};

function when(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("vi-VN",
    {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
}

function TaskChip({t, onRemove}: {t: Row; onRemove?: () => void}) {
  const closed = t.status === "done" || t.status === "cancelled";
  return <span style={{display: "inline-flex", gap: 6, alignItems: "center",
                       border: "1px solid var(--line)", borderRadius: 999,
                       padding: "3px 4px 3px 10px", fontSize: 12.5, margin: "0 6px 6px 0",
                       opacity: closed ? .7 : 1}}>
    <Link href={`/app/tasks/${t.id}`}>#{t.id} {t.title}</Link>
    <small style={{color: closed ? "var(--muted)" : "var(--accent)"}}>
      {STATUS_VI[t.status] || t.status}</small>
    {onRemove && <button aria-label={`Gỡ #${t.id}`} onClick={onRemove}
      style={{border: "none", background: "none", padding: "0 6px", fontSize: 14,
              color: "var(--muted)", cursor: "pointer"}}>×</button>}
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
    } catch (e) { setError(errorText(e, "Không tải được liên kết")); }
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

  if (!graph) return <div className="panel"><div className="v8Empty">
    {error || "Đang tải liên kết…"}</div></div>;

  const linked = new Set<number>([taskId, ...graph.blocked_by.map((t: Row) => t.id)]);
  const parentId = graph.parents[0]?.id;
  const ownGoal = graph.goal && !graph.goal.inherited ? graph.goal.id : null;

  return <div className="panel" data-testid="task-links">
    <div className="panelHead">
      <div><b>Liên kết</b></div>
      <small>mục tiêu · cha/con · phụ thuộc</small>
    </div>

    <div style={{fontSize: 12.5, color: "var(--muted)"}}>Chuỗi mục tiêu (agent nhận đúng dòng này)</div>
    <div data-testid="goal-line" style={{fontSize: 13.5, margin: "4px 0 12px", lineHeight: 1.5}}>
      {graph.goal_line}
    </div>

    {!!graph.open_blocker_ids.length && <div className="v8Error" style={{marginBottom: 10}}>
      Còn bị chặn bởi {graph.open_blocker_ids.map((i: number) => `#${i}`).join(", ")}:
      chưa chuyển sang đang làm/chờ duyệt/xong được, và chưa giao cho agent được.
    </div>}

    <label style={{fontSize: 12.5, fontWeight: 600}}>Mục tiêu</label>
    <select value={ownGoal ?? ""} disabled={busy}
            onChange={e => act(() => apiTask.setLinks(taskId,
              {goal_id: e.target.value ? Number(e.target.value) : null}))}
            style={{width: "100%", padding: 8, borderRadius: 9, margin: "4px 0 4px",
                    border: "1px solid var(--line)"}}>
      <option value="">{graph.goal?.inherited ? `— kế thừa: ${graph.goal.title} —`
                                              : "— chưa gắn mục tiêu —"}</option>
      {goals.map(g => <option key={g.id} value={g.id}>{g.title}</option>)}
    </select>

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 10}}>Việc cha</label>
    <select value={parentId ?? ""} disabled={busy}
            onChange={e => act(() => apiTask.setLinks(taskId,
              {parent_task_id: e.target.value ? Number(e.target.value) : null}))}
            style={{width: "100%", padding: 8, borderRadius: 9, marginTop: 4,
                    border: "1px solid var(--line)"}}>
      <option value="">— không có —</option>
      {tasks.map(t => <option key={t.id} value={t.id}>#{t.id} {t.title}</option>)}
    </select>

    {!!graph.children.length && <>
      <div style={{fontSize: 12.5, fontWeight: 600, marginTop: 10}}>Việc con</div>
      <div style={{marginTop: 4}}>{graph.children.map((t: Row) => <TaskChip key={t.id} t={t}/>)}</div>
    </>}

    <div style={{fontSize: 12.5, fontWeight: 600, marginTop: 12}}>Đang chờ việc</div>
    <div style={{marginTop: 4}}>
      {graph.blocked_by.length
        ? graph.blocked_by.map((t: Row) =>
            <TaskChip key={t.id} t={t}
                      onRemove={() => act(() => apiTask.removeBlocker(taskId, t.id))}/>)
        : <small style={{color: "var(--muted)"}}>Không chờ việc nào.</small>}
    </div>
    <div style={{display: "flex", gap: 6, marginTop: 4}}>
      <select value={blocker} onChange={e => setBlocker(e.target.value)} disabled={busy}
              aria-label="Chọn việc phải xong trước"
              style={{flex: 1, padding: 8, borderRadius: 9, border: "1px solid var(--line)"}}>
        <option value="">— thêm việc phải xong trước —</option>
        {tasks.filter(t => !linked.has(t.id)).map(t =>
          <option key={t.id} value={t.id}>#{t.id} {t.title}</option>)}
      </select>
      <button disabled={busy || !blocker}
              onClick={() => act(async () => {
                const out = await apiTask.addBlocker(taskId, Number(blocker));
                setBlocker(""); return out;
              })}>Thêm</button>
    </div>

    {!!graph.blocking.length && <>
      <div style={{fontSize: 12.5, fontWeight: 600, marginTop: 12}}>Đang chặn</div>
      <div style={{marginTop: 4}}>{graph.blocking.map((t: Row) => <TaskChip key={t.id} t={t}/>)}</div>
    </>}

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 12}}>
      Tiêu chí nghiệm thu
    </label>
    <textarea value={criteria} onChange={e => setCriteria(e.target.value)} rows={3}
              placeholder="Thế nào thì coi là xong? Agent đọc dòng này ở khối 2."
              style={{width: "100%", padding: 9, borderRadius: 9, marginTop: 4,
                      border: "1px solid var(--line)", fontSize: 13}}/>
    <button disabled={busy || criteria === (graph.acceptance_criteria || "")}
            onClick={() => act(() => apiTask.setLinks(taskId, {acceptance_criteria: criteria}))}
            style={{marginTop: 6}}>Lưu tiêu chí</button>

    {error && <div className="v8Error" style={{marginTop: 10}}>{error}</div>}
  </div>;
}

export function TaskRunsPanel({taskId, refreshKey = 0}: {taskId: number; refreshKey?: number}) {
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    apiTask.runs(taskId).then(setData).catch(e => setError(errorText(e)));
  }, [taskId, refreshKey]);

  const runs: Row[] = data?.runs || [];
  return <div className="panel" data-testid="task-runs">
    <div className="panelHead">
      <div><b>Lượt chạy</b></div>
      <small>task_runs · {runs.length}</small>
    </div>
    {error && <div className="v8Error">{error}</div>}
    {!error && !runs.length && <div className="v8Empty">
      Chưa có lượt chạy nào. Lượt đầu tiên được ghi khi việc được giao cho agent.
    </div>}
    <div style={{display: "grid", gap: 8}}>
      {runs.map(r => {
        const s = RUN_VI[r.status] || {text: r.status, cls: "mid"};
        return <div key={r.id} style={{border: "1px solid var(--line)", borderRadius: 10,
                                       padding: "8px 10px", fontSize: 12.5}}>
          <div style={{display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap"}}>
            <b>Lượt #{r.id}</b>
            <span className={`prio ${s.cls}`}>{s.text}</span>
            {r.holds_task && <small style={{color: "var(--accent)"}}>đang giữ việc</small>}
            <small style={{color: "var(--muted)", marginLeft: "auto"}}>
              {r.member_name || "—"} · {r.trigger_kind}
            </small>
          </div>
          <div style={{color: "var(--muted)", marginTop: 3}}>
            bắt đầu {when(r.started_at || r.created_at)} · kết thúc {when(r.ended_at)}
            {r.cost_usd ? ` · $${Number(r.cost_usd).toFixed(4)}` : ""}
          </div>
          {r.error_reason && <div style={{marginTop: 3}}>Lý do: {r.error_reason}</div>}
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
  if (rows === null) return <div className="v8Empty">Đang tải việc…</div>;
  if (!rows.length) return <div className="v8Empty">
    Chưa có việc nào gắn vào mục tiêu này. Gắn ở màn hình chi tiết việc → Liên kết.
  </div>;
  return <div className="v9List">{rows.map(t =>
    <div className="v9Cycle" key={t.id}>
      <div><b><Link href={`/app/tasks/${t.id}`}>#{t.id} {t.title}</Link></b>
        <small>{STATUS_VI[t.status] || t.status} · ưu tiên {t.priority}</small></div>
    </div>)}</div>;
}


/* D2.1 — vì sao seat được (hoặc không được) đánh thức cho việc này. */
const WAKE_REASON_VI: Record<string, string> = {
  assigned: "được giao việc", mentioned: "được nhắc tên", handoff: "nhận bàn giao",
  approval_resolved: "approval có kết quả", blocker_cleared: "hết bị chặn",
  review_requested: "được nhờ review", routine: "lịch định kỳ", goal_created: "mục tiêu mới",
};
const WAKE_STATUS_VI: Record<string, {text: string; cls: string}> = {
  queued: {text: "đang chờ gộp", cls: "mid"}, dispatched: {text: "đã chạy", cls: "low"},
  coalesced: {text: "gộp vào lượt khác", cls: "low"}, skipped: {text: "bỏ qua", cls: "high"},
  failed: {text: "lỗi", cls: "high"},
};

// Mã lý do giữ nguyên (để tra log/API), chỉ thêm câu tiếng Việt đứng trước.
const SKIP_VI: [string, string][] = [
  ["seat_busy", "Seat đang bận một lượt khác — sẽ tự xếp lại khi lượt đó xong"],
  ["budget", "Hết ngân sách"], ["outside_active_hours", "Ngoài giờ làm của agent"],
  ["seat_inactive", "Seat đang tắt"], ["not_an_agent_seat", "Seat không phải agent"],
  ["not_assignee", "Người được nhắc không phải người nhận việc"],
  ["task_status", "Việc không ở trạng thái chạy được"], ["dispatch_error", "Không gửi được cho agent"],
  ["runtime_error", "Gateway lỗi"],
];
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
  return <div className="panel" data-testid="task-wakeups">
    <div className="panelHead">
      <div><b>Đánh thức</b></div>
      <small>wakeups · {list.length}</small>
    </div>
    {error && <div className="v8Error">{error}</div>}
    {!error && rows && !list.length && <div className="v8Empty">
      Chưa có lý do nào để đánh thức seat. Giao việc cho agent, nhắc @tên trong sổ,
      hoặc đóng việc đang chặn thì sẽ có.
    </div>}
    <div style={{display: "grid", gap: 8}}>
      {list.map(w => {
        const s = WAKE_STATUS_VI[w.status] || {text: w.status, cls: "mid"};
        return <div key={w.id} data-testid="wakeup-row"
                    style={{border: "1px solid var(--line)", borderRadius: 10, padding: "8px 10px", fontSize: 12.5}}>
          <div style={{display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap"}}>
            <b>{WAKE_REASON_VI[w.reason] || w.reason}</b>
            <span className={`prio ${s.cls}`}>{s.text}</span>
            <small style={{color: "var(--muted)", marginLeft: "auto"}}>
              {when(w.created_at)}{w.run_id ? ` · lượt #${w.run_id}` : ""}
            </small>
          </div>
          {w.skip_reason && <div style={{marginTop: 3}}>Lý do: {skipText(w.skip_reason)}</div>}
          {w.coalesced_into_id && <div style={{marginTop: 3, color: "var(--muted)"}}>
            Gộp cùng lượt với lý do #{w.coalesced_into_id} (trong cửa sổ 10 giây).
          </div>}
        </div>;
      })}
    </div>
  </div>;
}
