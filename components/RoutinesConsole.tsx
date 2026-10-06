"use client";
// D3.4 — Việc định kỳ: routine = việc gì (runbook) + giao ai (seat/phòng) +
// khi nào (cron theo múi giờ, webhook). Mỗi lần chạy có idempotency key nên
// không có việc trùng; lỗi liên tiếp quá ngưỡng → routine tự dừng và báo Hộp việc.
import {useEffect, useState} from "react";
import {AuthGate} from "./AuthGate";
import {V9AppShell} from "./V9AppShell";
import {api, apiRoutines, errorText} from "../lib/api";

const ST_VI: Record<string, string> = {queued: "đang chờ", running: "đang chạy", succeeded: "xong", failed: "lỗi", skipped: "bỏ qua"};
const ST_COLOR: Record<string, string> = {queued: "#8a6d00", running: "#1f5fbf", succeeded: "#16794c", failed: "#b42318", skipped: "#777"};
const KIND_VI: Record<string, string> = {cron: "theo lịch", webhook: "webhook", manual: "chạy tay", catch_up: "chạy bù"};
const when = (s?: string | null) => s ? new Date(s).toLocaleString("vi-VN", {dateStyle: "short", timeStyle: "short"}) : "—";

export function RoutinesConsole() {
  const [rows, setRows] = useState<any[]>([]), [tpls, setTpls] = useState<any[]>([]);
  const [members, setMembers] = useState<any[]>([]), [departments, setDepartments] = useState<any[]>([]);
  const [sel, setSel] = useState<number | null>(null), [detail, setDetail] = useState<any>(null), [runs, setRuns] = useState<any[]>([]);
  const [form, setForm] = useState<any>({name: "", runbook: "", target: "", cron: "0 9 * * 1-5", timezone: "Asia/Ho_Chi_Minh",
    catch_up: "skip_missed", mode: "create_task", webhook: false, max_consecutive_failures: 3});
  const [error, setError] = useState(""), [note, setNote] = useState("");

  async function load() {
    try { const d = await apiRoutines.list(); setRows(d.routines || []); if (sel == null && d.routines?.[0]) setSel(d.routines[0].id); }
    catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => {
    load();
    apiRoutines.templates().then((x: any) => setTpls(x.templates || [])).catch(() => {});
    api.members().then((x: any) => setMembers(x || [])).catch(() => {});
    api.departments().then((x: any) => setDepartments(x || [])).catch(() => {});
  }, []);
  async function open(id = sel) {
    if (id == null) return;
    try { const [d, r] = await Promise.all([apiRoutines.get(id), apiRoutines.runs(id)]); setDetail(d); setRuns(r.runs || []); }
    catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => { open(); }, [sel]);
  const names: Record<number, string> = Object.fromEntries(members.map((m: any) => [m.id, m.name]));
  const deptNames: Record<number, string> = Object.fromEntries(departments.map((d: any) => [d.id, d.name]));
  const who = (r: any) => r.department_id ? `phòng ${deptNames[r.department_id] || "#" + r.department_id}` : (names[r.assignee_member_id] || "#" + r.assignee_member_id);

  async function act(fn: () => Promise<any>, ok: (x: any) => string) {
    setError(""); setNote("");
    try { const x = await fn(); setNote(ok(x)); await load(); await open(x?.id && !x?.run_id ? x.id : sel); if (x?.id && !x?.run_id) setSel(x.id); }
    catch (e: any) { setError(errorText(e)); }
  }
  function create() {
    const [kind, id] = String(form.target).split(":");
    const body: any = {...form, assignee_member_id: kind === "m" ? Number(id) : null, department_id: kind === "d" ? Number(id) : null};
    delete body.target;
    if (!body.cron) delete body.cron;
    act(() => apiRoutines.create(body), (x: any) => `Đã tạo routine #${x.id}.`);
  }
  const set = (k: string) => (e: any) => setForm({...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});

  return <AuthGate><V9AppShell title="Việc định kỳ" subtitle="Routine theo lịch (múi giờ của routine) hoặc webhook · mỗi lần chạy một khoá, không bao giờ trùng việc">
    {error && <div className="v8Error" data-testid="routines-error">{error}</div>}
    {note && <div className="v8Card" style={{padding: 10, marginBottom: 10, borderLeft: "3px solid #16794c"}} data-testid="routines-note">{note}</div>}
    <div className="v9Grid2">
      <section className="v8Card">
        <div className="v8CardHead"><div><b>Routine</b><span>{rows.length} routine · bấm để xem lần chạy</span></div>
          <button className="v8Ghost" onClick={() => act(() => apiRoutines.tick(), (x: any) => `Nhịp lịch: ${x.fired.length} kích hoạt.`)}>Chạy nhịp lịch ngay</button></div>
        <div className="v9List" data-testid="routines-list">
          {rows.map((r: any) => {
            const cron = r.triggers.find((t: any) => t.kind === "cron"), last = r.last_run;
            return <button key={r.id} className="v9BudgetButton" onClick={() => setSel(r.id)} data-testid={`routine-${r.id}`}
              style={{textAlign: "left", outline: r.id === sel ? "2px solid #1f5fbf" : undefined}}>
              <div style={{display: "flex", justifyContent: "space-between"}}><b>{r.name}</b>
                <small style={{color: r.enabled ? "#16794c" : "#b42318"}}>{r.enabled ? "đang bật" : "đã dừng"}</small></div>
              <small>{who(r)} · {cron ? `${cron.cron} (${r.timezone}) · lần tới ${cron.next_run_local || "—"}` : "chỉ webhook"}</small>
              {last && <div style={{fontSize: 12, color: ST_COLOR[last.status]}}>Lần cuối: {ST_VI[last.status]} · {when(last.created_at)}</div>}
              {!r.enabled && r.paused_reason && <div style={{fontSize: 12, color: "#b42318"}}>⚠ {r.paused_reason}</div>}
            </button>;
          })}
          {!rows.length && <div className="v9Empty">Chưa có routine. Tạo từ mẫu bên dưới.</div>}
        </div>
        <div className="v9Form" style={{marginTop: 12}}>
          <b>Tạo từ mẫu</b>
          {tpls.map((t: any) => <div key={t.key} style={{display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8}}>
            <small><b>{t.name}</b> · {t.cron} ({t.timezone})</small>
            <button className="v8Ghost" data-testid={`tpl-${t.key}`}
              onClick={() => { const [k, id] = String(form.target).split(":"); act(() => apiRoutines.fromTemplate(t.key, k === "m" ? Number(id) : null, k === "d" ? Number(id) : null), (x: any) => `Đã tạo “${x.name}” cho ${who(x)}.`); }}>Tạo</button>
          </div>)}
          <small>Người nhận lấy theo ô “Giao cho” ở form bên phải; để trống thì mẫu giao seat Nina.</small>
        </div>
      </section>
      <section className="v8Card">
        {detail ? <>
          <div className="v8CardHead"><div><b>#{detail.id} {detail.name}</b>
            <span>{detail.mode === "run_only" ? "đánh thức trên việc thường trực" : "mỗi lần một việc mới"} · chạy bù: {detail.catch_up === "run_once" ? "chạy bù 1 lần" : "bỏ giờ lỡ"} · lỗi {detail.consecutive_failures}/{detail.max_consecutive_failures}</span></div>
            <div style={{display: "flex", gap: 6}}>
              <button className="v8Primary" disabled={!detail.enabled} onClick={() => act(() => apiRoutines.run(detail.id), (x: any) => `Lần chạy #${x.run_id}: ${ST_VI[x.status] || x.status}${x.task_id ? ` · task #${x.task_id}` : ""}.`)} data-testid="routine-run">Chạy ngay</button>
              <button className="v8Ghost" onClick={() => act(() => apiRoutines.setEnabled(detail.id, !detail.enabled), (x: any) => x.enabled ? "Đã bật lại (xoá chuỗi lỗi, lịch tính từ bây giờ)." : "Đã tắt.")} data-testid="routine-toggle">{detail.enabled ? "Tắt" : "Bật lại"}</button>
            </div></div>
          {detail.triggers.filter((t: any) => t.kind === "webhook").map((t: any) => <div key={t.id} style={{fontSize: 12, background: "#f6f6f6", padding: 8, borderRadius: 6, marginBottom: 8}} data-testid="routine-hook">
            <b>Webhook</b>: POST <code>{t.hook_path}</code><br/>Header <code>X-Routine-Secret: {t.secret}</code> và <code>Idempotency-Key</code> (bắt buộc — gửi lại cùng khoá không tạo việc mới).</div>)}
          {detail.runbook && <pre style={{whiteSpace: "pre-wrap", fontSize: 12, background: "#fafafa", padding: 8, borderRadius: 6}}>{detail.runbook}</pre>}
          <b style={{fontSize: 13}}>Các lần chạy</b>
          <table style={{width: "100%", fontSize: 12, borderCollapse: "collapse", marginTop: 4}} data-testid="routine-runs"><tbody>
            {runs.map((x: any) => <tr key={x.run_id} style={{borderBottom: "1px solid #eee"}}>
              <td style={{padding: "4px 0"}}>#{x.run_id} · {KIND_VI[x.kind] || x.kind}<br/><small>{when(x.scheduled_for || x.created_at)}</small></td>
              <td style={{color: ST_COLOR[x.status]}}>{ST_VI[x.status] || x.status}</td>
              <td>{x.task_id ? <a href={`/app/tasks/${x.task_id}`}>task #{x.task_id}</a> : "—"}</td>
              <td style={{maxWidth: 220}}><small style={{color: "#666"}}>{x.error}</small></td>
            </tr>)}
          </tbody></table>
          {!runs.length && <div className="v9Empty">Chưa chạy lần nào.</div>}
        </> : <div className="v9Empty">Chọn một routine.</div>}
        <div className="v9Form" style={{marginTop: 16}}>
          <b>Routine mới</b>
          <div className="v9FormRow">
            <label>Tên<input value={form.name} onChange={set("name")} data-testid="rf-name" placeholder="VD: Đối soát đơn hàng"/></label>
            <label>Giao cho<select value={form.target} onChange={set("target")} data-testid="rf-target">
              <option value="">— chọn —</option>
              <optgroup label="Seat / người">{members.map((m: any) => <option key={m.id} value={`m:${m.id}`}>{m.name}{m.member_type === "agent" ? " (AI)" : ""}</option>)}</optgroup>
              <optgroup label="Phòng (trưởng phòng định tuyến)">{departments.map((d: any) => <option key={d.id} value={`d:${d.id}`}>{d.name}</option>)}</optgroup>
            </select></label>
          </div>
          <textarea rows={3} value={form.runbook} onChange={set("runbook")} placeholder="Runbook: việc cần làm mỗi lần chạy" style={{width: "100%"}}/>
          <div className="v9FormRow">
            <label>Cron (5 trường)<input value={form.cron} onChange={set("cron")} data-testid="rf-cron" placeholder="30 8 * * *"/></label>
            <label>Múi giờ<input value={form.timezone} onChange={set("timezone")}/></label>
          </div>
          <div className="v9FormRow">
            <label>Giờ lỡ khi hệ thống tắt<select value={form.catch_up} onChange={set("catch_up")}>
              <option value="skip_missed">Bỏ (ghi lại là bỏ qua)</option><option value="run_once">Chạy bù 1 lần</option></select></label>
            <label>Kiểu<select value={form.mode} onChange={set("mode")}>
              <option value="create_task">Mỗi lần một việc mới</option><option value="run_only">Chỉ đánh thức (việc thường trực)</option></select></label>
            <label>Tự dừng sau N lỗi<input type="number" min={1} value={form.max_consecutive_failures} onChange={e => setForm({...form, max_consecutive_failures: Number(e.target.value)})}/></label>
          </div>
          <label style={{fontSize: 13}}><input type="checkbox" checked={form.webhook} onChange={set("webhook")}/> Thêm webhook</label>
          <button className="v8Primary" onClick={create} disabled={!form.name || !form.target} data-testid="rf-submit">Tạo routine</button>
        </div>
      </section>
    </div>
  </V9AppShell></AuthGate>;
}
