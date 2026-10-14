"use client";
// D3.4 — Việc định kỳ: routine = việc gì (runbook) + giao ai (seat/phòng) +
// khi nào (cron theo múi giờ, webhook). Mỗi lần chạy có idempotency key nên
// không có việc trùng; lỗi liên tiếp quá ngưỡng → routine tự dừng và báo Hộp việc.
import Link from "next/link";
import {useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiRoutines} from "../lib/api";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill, Tone} from "./ui/StatusPill";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {useToast} from "./ui/Toast";

const ST_VI: Record<string, string> = {queued: "đang chờ", running: "đang chạy", succeeded: "xong", failed: "lỗi", skipped: "bỏ qua"};
const ST_TONE: Record<string, Tone> = {queued: "wait", running: "ok", succeeded: "ok", failed: "risk", skipped: "neutral"};
const KIND_VI: Record<string, string> = {cron: "theo lịch", webhook: "webhook", manual: "chạy tay", catch_up: "chạy bù"};
const when = (s?: string | null) => s ? new Date(s).toLocaleString("vi-VN", {dateStyle: "short", timeStyle: "short"}) : "—";

export function RoutinesConsole() {
  const [rows, setRows] = useState<any[]>([]), [tpls, setTpls] = useState<any[]>([]);
  const [members, setMembers] = useState<any[]>([]), [departments, setDepartments] = useState<any[]>([]);
  const [sel, setSel] = useState<number | null>(null), [detail, setDetail] = useState<any>(null), [runs, setRuns] = useState<any[]>([]);
  const [form, setForm] = useState<any>({name: "", runbook: "", target: "", cron: "0 9 * * 1-5", timezone: "Asia/Ho_Chi_Minh",
    catch_up: "skip_missed", mode: "create_task", webhook: false, max_consecutive_failures: 3});
  const [error, setError] = useState<unknown>(null);
  const toast = useToast(); const setNote = (m: string) => { if (m) toast(m); };

  async function load() {
    try { const d = await apiRoutines.list(); setRows(d.routines || []); if (sel == null && d.routines?.[0]) setSel(d.routines[0].id); }
    catch (e: any) { setError(e); }
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
    catch (e: any) { setError(e); }
  }
  useEffect(() => { open(); }, [sel]);
  const names: Record<number, string> = Object.fromEntries(members.map((m: any) => [m.id, m.name]));
  const deptNames: Record<number, string> = Object.fromEntries(departments.map((d: any) => [d.id, d.name]));
  const who = (r: any) => r.department_id ? `phòng ${deptNames[r.department_id] || "#" + r.department_id}` : (names[r.assignee_member_id] || "#" + r.assignee_member_id);

  async function act(fn: () => Promise<any>, ok: (x: any) => string) {
    setError(null);
    try { const x = await fn(); setNote(ok(x)); await load(); await open(x?.id && !x?.run_id ? x.id : sel); if (x?.id && !x?.run_id) setSel(x.id); }
    catch (e: any) { setError(e); }
  }
  function create() {
    const [kind, id] = String(form.target).split(":");
    const body: any = {...form, assignee_member_id: kind === "m" ? Number(id) : null, department_id: kind === "d" ? Number(id) : null};
    delete body.target;
    if (!body.cron) delete body.cron;
    act(() => apiRoutines.create(body), (x: any) => `Đã tạo routine #${x.id}.`);
  }
  const set = (k: string) => (e: any) => setForm({...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});

  return <PageFrame action={<Button variant="ghost" size="sm" icon="play" onClick={() => act(() => apiRoutines.tick(), (x: any) => `Nhịp lịch: ${x.fired.length} routine được kích hoạt.`)}>Chạy nhịp lịch ngay</Button>}>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="routines-error"/> : null}
    <div className="ui-grid is-side-l">
      <div className="ui-grid">
        <Panel title="Routine" desc={`${rows.length} routine · bấm để xem lần chạy`} flush testId="routines-list">
          {!rows.length ? <EmptyState compact mood="chao" title="Chưa có routine">Tạo từ mẫu bên dưới, hoặc tự viết ở form “Routine mới”.</EmptyState>
            : <div className="ui-list">{rows.map((r: any) => {
              const cron = r.triggers.find((t: any) => t.kind === "cron"), last = r.last_run;
              return <button key={r.id} className="ui-row" onClick={() => setSel(r.id)} aria-pressed={r.id === sel} data-testid={`routine-${r.id}`}
                style={r.id === sel ? {background: "var(--selected)"} : undefined}>
                <span className="ui-row-main"><span className="ui-row-title">{r.name}</span>
                  <span className="ui-row-meta">{who(r)} · {cron ? `${cron.cron} · lần tới ${cron.next_run_local || "—"}` : "chỉ webhook"}</span>
                  {!r.enabled && r.paused_reason && <span className="ui-row-meta" style={{color: "var(--risk)"}}>Đã tự dừng: {r.paused_reason}</span>}</span>
                <span className="ui-row-end" style={{flexDirection: "column", alignItems: "flex-end", gap: 4}}>
                  <StatusPill tone={r.enabled ? "ok" : "risk"}>{r.enabled ? "Đang bật" : "Đã dừng"}</StatusPill>
                  {last && <small>{ST_VI[last.status]} · {when(last.created_at)}</small>}</span>
              </button>; })}</div>}
        </Panel>
        <Panel title="Tạo từ mẫu" desc="Người nhận lấy theo ô “Giao cho” trong form Routine mới; để trống thì giao Nina" flush>
          <div className="ui-list">{tpls.map((t: any) => <div key={t.key} className="ui-row">
            <span className="ui-row-main"><span className="ui-row-title">{t.name}</span><span className="ui-row-meta">{t.cron} ({t.timezone})</span></span>
            <Button size="sm" data-testid={`tpl-${t.key}`}
              onClick={() => { const [k, id] = String(form.target).split(":"); act(() => apiRoutines.fromTemplate(t.key, k === "m" ? Number(id) : null, k === "d" ? Number(id) : null), (x: any) => `Đã tạo “${x.name}” cho ${who(x)}.`); }}>Tạo</Button>
          </div>)}{!tpls.length && <p className="ui-row ui-row-meta">Không có mẫu.</p>}</div>
        </Panel>
      </div>
      <div className="ui-grid">
        <Panel title={detail ? `#${detail.id} ${detail.name}` : "Chọn một routine"} testId="routine-detail"
          desc={detail ? `${detail.mode === "run_only" ? "Đánh thức trên việc thường trực" : "Mỗi lần một việc mới"} · chạy bù: ${detail.catch_up === "run_once" ? "1 lần" : "bỏ giờ lỡ"} · lỗi liên tiếp ${detail.consecutive_failures}/${detail.max_consecutive_failures}` : "Lần chạy, webhook và runbook hiện ở đây"}
          actions={detail ? <>
            <Button size="sm" variant="primary" icon="play" disabled={!detail.enabled} onClick={() => act(() => apiRoutines.run(detail.id), (x: any) => `Lần chạy #${x.run_id}: ${ST_VI[x.status] || x.status}${x.task_id ? ` · việc #${x.task_id}` : ""}.`)} data-testid="routine-run">Chạy ngay</Button>
            <Button size="sm" onClick={() => act(() => apiRoutines.setEnabled(detail.id, !detail.enabled), (x: any) => x.enabled ? "Đã bật lại (xoá chuỗi lỗi, lịch tính từ bây giờ)." : "Đã tắt routine.")} data-testid="routine-toggle">{detail.enabled ? "Tắt" : "Bật lại"}</Button></> : undefined}>
          {!detail ? <EmptyState compact mood="ngu" title="Chưa chọn routine">Chọn một routine trong danh sách để xem lần chạy.</EmptyState> : <div className="ui-grid" style={{gap: 12}}>
            {detail.triggers.filter((t: any) => t.kind === "webhook").map((t: any) => <div key={t.id} className="gl-summary" data-testid="routine-hook">
              <b>Webhook</b>: POST <code translate="no">{t.hook_path}</code><br/>Gửi kèm header <code translate="no">X-Routine-Secret: {t.secret}</code> và <code translate="no">Idempotency-Key</code> (bắt buộc — gửi lại cùng khoá không tạo việc mới).</div>)}
            {detail.runbook && <pre className="gl-summary">{detail.runbook}</pre>}
            <div className="ui-table-wrap"><table className="ui-table" data-testid="routine-runs">
              <thead><tr><th>Lần chạy</th><th>Kết quả</th><th>Việc</th><th>Ghi chú</th></tr></thead>
              <tbody>{runs.map((x: any) => <tr key={x.run_id}>
                <td>#{x.run_id} · {KIND_VI[x.kind] || x.kind}<br/><small>{when(x.scheduled_for || x.created_at)}</small></td>
                <td><StatusPill tone={ST_TONE[x.status] || "neutral"}>{ST_VI[x.status] || x.status}</StatusPill></td>
                <td>{x.task_id ? <Link href={`/app/work?peek=${x.task_id}`}>việc #{x.task_id}</Link> : "—"}</td>
                <td style={{maxWidth: 240}}><small>{x.error}</small></td>
              </tr>)}</tbody></table></div>
            {!runs.length && <p className="ui-empty-line">Chưa chạy lần nào.</p>}
          </div>}
        </Panel>
        <Panel title="Routine mới" desc="Việc gì · giao ai · khi nào">
          <form className="ui-form" onSubmit={e => { e.preventDefault(); create(); }}>
            <FormRow>
              <Field label="Tên"><input value={form.name} onChange={set("name")} data-testid="rf-name" placeholder="VD: Đối soát đơn hàng…" autoComplete="off"/></Field>
              <Field label="Giao cho"><select value={form.target} onChange={set("target")} data-testid="rf-target">
                <option value="">— chọn —</option>
                <optgroup label="Seat / người">{members.map((m: any) => <option key={m.id} value={`m:${m.id}`}>{m.name}{m.member_type === "agent" ? " (AI)" : ""}</option>)}</optgroup>
                <optgroup label="Phòng (trưởng phòng định tuyến)">{departments.map((d: any) => <option key={d.id} value={`d:${d.id}`}>{d.name}</option>)}</optgroup>
              </select></Field>
            </FormRow>
            <Field label="Runbook" hint="Việc cần làm mỗi lần chạy — agent nhận nguyên văn"><textarea rows={3} value={form.runbook} onChange={set("runbook")} placeholder="VD: Lấy đơn mới từ sàn, đối chiếu tồn kho, báo lệch…"/></Field>
            <FormRow>
              <Field label="Lịch (cron 5 trường)" hint="VD 30 8 * * * = 8:30 mỗi ngày"><input value={form.cron} onChange={set("cron")} data-testid="rf-cron" placeholder="30 8 * * *" spellCheck={false}/></Field>
              <Field label="Múi giờ"><input value={form.timezone} onChange={set("timezone")} spellCheck={false}/></Field>
            </FormRow>
            <FormRow>
              <Field label="Giờ lỡ khi hệ thống tắt"><select value={form.catch_up} onChange={set("catch_up")}>
                <option value="skip_missed">Bỏ (ghi là bỏ qua)</option><option value="run_once">Chạy bù 1 lần</option></select></Field>
              <Field label="Kiểu"><select value={form.mode} onChange={set("mode")}>
                <option value="create_task">Mỗi lần một việc mới</option><option value="run_only">Chỉ đánh thức (việc thường trực)</option></select></Field>
              <Field label="Tự dừng sau N lỗi"><input type="number" min={1} value={form.max_consecutive_failures} onChange={e => setForm({...form, max_consecutive_failures: Number(e.target.value)})}/></Field>
            </FormRow>
            <label className="ui-check"><input type="checkbox" checked={form.webhook} onChange={set("webhook")}/> Thêm webhook để hệ thống khác kích hoạt</label>
            <Button type="submit" variant="primary" disabled={!form.name || !form.target} data-testid="rf-submit">Tạo routine</Button>
          </form>
        </Panel>
      </div>
    </div>
  </PageFrame>;
}
