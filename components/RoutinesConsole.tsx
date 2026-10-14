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
import {t as tr, lazy, intlLocale} from "../lib/i18n";

const ST_VI: Record<string, string> = lazy(() => ({queued: tr("routines.dang_cho"), running: tr("routines.dang_chay"), succeeded: "xong", failed: tr("routines.loi"), skipped: tr("routines.bo_qua")}));
const ST_TONE: Record<string, Tone> = {queued: "wait", running: "ok", succeeded: "ok", failed: "risk", skipped: "neutral"};
const KIND_VI: Record<string, string> = lazy(() => ({cron: tr("routines.theo_lich"), webhook: "webhook", manual: tr("routines.chay_tay"), catch_up: tr("routines.chay_bu")}));
const when = (s?: string | null) => s ? new Date(s).toLocaleString(intlLocale(), {dateStyle: "short", timeStyle: "short"}) : "—";

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
  const who = (r: any) => r.department_id ? tr("routines.phong", {p0: deptNames[r.department_id] || "#" + r.department_id}) : (names[r.assignee_member_id] || "#" + r.assignee_member_id);

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
    act(() => apiRoutines.create(body), (x: any) => tr("routines.da_tao_routine", {p0: x.id}));
  }
  const set = (k: string) => (e: any) => setForm({...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});

  return <PageFrame action={<Button variant="ghost" size="sm" icon="play" onClick={() => act(() => apiRoutines.tick(), (x: any) => tr("routines.nhip_lich_routine_duoc_kich", {p0: x.fired.length}))}>{tr("routines.chay_nhip_lich_ngay")}</Button>}>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="routines-error"/> : null}
    <div className="ui-grid is-side-l">
      <div className="ui-grid">
        <Panel title="Routine" desc={tr("routines.routine_bam_de_xem_lan", {p0: rows.length})} flush testId="routines-list">
          {!rows.length ? <EmptyState compact mood="chao" title={tr("routines.chua_co_routine")}>{tr("routines.tao_tu_mau_ben_duoi")}</EmptyState>
            : <div className="ui-list">{rows.map((r: any) => {
              const cron = r.triggers.find((t: any) => t.kind === "cron"), last = r.last_run;
              return <button key={r.id} className="ui-row" onClick={() => setSel(r.id)} aria-pressed={r.id === sel} data-testid={`routine-${r.id}`}
                style={r.id === sel ? {background: "var(--selected)"} : undefined}>
                <span className="ui-row-main"><span className="ui-row-title">{r.name}</span>
                  <span className="ui-row-meta">{who(r)} · {cron ? tr("routines.lan_toi", {p0: cron.cron, p1: cron.next_run_local || "—"}) : tr("routines.chi_webhook")}</span>
                  {!r.enabled && r.paused_reason && <span className="ui-row-meta" style={{color: "var(--risk)"}}>{tr("routines.da_tu_dung")} {r.paused_reason}</span>}</span>
                <span className="ui-row-end" style={{flexDirection: "column", alignItems: "flex-end", gap: 4}}>
                  <StatusPill tone={r.enabled ? "ok" : "risk"}>{r.enabled ? tr("routines.dang_bat") : tr("routines.da_dung")}</StatusPill>
                  {last && <small>{ST_VI[last.status]} · {when(last.created_at)}</small>}</span>
              </button>; })}</div>}
        </Panel>
        <Panel title={tr("routines.tao_tu_mau")} desc={tr("routines.nguoi_nhan_lay_theo_o")} flush>
          <div className="ui-list">{tpls.map((t: any) => <div key={t.key} className="ui-row">
            <span className="ui-row-main"><span className="ui-row-title">{t.name}</span><span className="ui-row-meta">{t.cron} ({t.timezone})</span></span>
            <Button size="sm" data-testid={`tpl-${t.key}`}
              onClick={() => { const [k, id] = String(form.target).split(":"); act(() => apiRoutines.fromTemplate(t.key, k === "m" ? Number(id) : null, k === "d" ? Number(id) : null), (x: any) => tr("routines.da_tao_cho", {p0: x.name, p1: who(x)})); }}>{tr("routines.tao")}</Button>
          </div>)}{!tpls.length && <p className="ui-row ui-row-meta">{tr("routines.khong_co_mau")}</p>}</div>
        </Panel>
      </div>
      <div className="ui-grid">
        <Panel title={detail ? `#${detail.id} ${detail.name}` : tr("routines.chon_mot_routine")} testId="routine-detail"
          desc={detail ? tr("routines.chay_bu_loi_lien_tiep", {p0: detail.mode === "run_only" ? "Đánh thức trên việc thường trực" : "Mỗi lần một việc mới", p1: detail.catch_up === "run_once" ? "1 lần" : "bỏ giờ lỡ", p2: detail.consecutive_failures, p3: detail.max_consecutive_failures}) : tr("routines.lan_chay_webhook_va_runbook")}
          actions={detail ? <>
            <Button size="sm" variant="primary" icon="play" disabled={!detail.enabled} onClick={() => act(() => apiRoutines.run(detail.id), (x: any) => tr("routines.lan_chay", {p0: x.run_id, p1: ST_VI[x.status] || x.status, p2: x.task_id ? ` · việc #${x.task_id}` : ""}))} data-testid="routine-run">{tr("routines.chay_ngay")}</Button>
            <Button size="sm" onClick={() => act(() => apiRoutines.setEnabled(detail.id, !detail.enabled), (x: any) => x.enabled ? tr("routines.da_bat_lai_xoa_chuoi") : tr("routines.da_tat_routine"))} data-testid="routine-toggle">{detail.enabled ? tr("routines.tat") : tr("routines.bat_lai")}</Button></> : undefined}>
          {!detail ? <EmptyState compact mood="ngu" title={tr("routines.chua_chon_routine")}>{tr("routines.chon_mot_routine_trong_danh")}</EmptyState> : <div className="ui-grid" style={{gap: 12}}>
            {detail.triggers.filter((t: any) => t.kind === "webhook").map((t: any) => <div key={t.id} className="gl-summary" data-testid="routine-hook">
              <b>Webhook</b>: POST <code translate="no">{t.hook_path}</code><br/>{tr("routines.gui_kem_header")} <code translate="no">X-Routine-Secret: {t.secret}</code> {tr("routines.va")} <code translate="no">Idempotency-Key</code> {tr("routines.bat_buoc_gui_lai_cung")}</div>)}
            {detail.runbook && <pre className="gl-summary">{detail.runbook}</pre>}
            <div className="ui-table-wrap"><table className="ui-table" data-testid="routine-runs">
              <thead><tr><th>{tr("routines.lan_chay_2")}</th><th>{tr("routines.ket_qua")}</th><th>{tr("routines.viec")}</th><th>{tr("routines.ghi_chu")}</th></tr></thead>
              <tbody>{runs.map((x: any) => <tr key={x.run_id}>
                <td>#{x.run_id} · {KIND_VI[x.kind] || x.kind}<br/><small>{when(x.scheduled_for || x.created_at)}</small></td>
                <td><StatusPill tone={ST_TONE[x.status] || "neutral"}>{ST_VI[x.status] || x.status}</StatusPill></td>
                <td>{x.task_id ? <Link href={`/app/work?peek=${x.task_id}`}>{tr("routines.viec_2")}{x.task_id}</Link> : "—"}</td>
                <td style={{maxWidth: 240}}><small>{x.error}</small></td>
              </tr>)}</tbody></table></div>
            {!runs.length && <p className="ui-empty-line">{tr("routines.chua_chay_lan_nao")}</p>}
          </div>}
        </Panel>
        <Panel title={tr("routines.routine_moi")} desc={tr("routines.viec_gi_giao_ai_khi")}>
          <form className="ui-form" onSubmit={e => { e.preventDefault(); create(); }}>
            <FormRow>
              <Field label={tr("routines.ten")}><input value={form.name} onChange={set("name")} data-testid="rf-name" placeholder={tr("routines.vd_doi_soat_don_hang")} autoComplete="off"/></Field>
              <Field label="Giao cho"><select value={form.target} onChange={set("target")} data-testid="rf-target">
                <option value="">{tr("routines.chon")}</option>
                <optgroup label={tr("routines.seat_nguoi")}>{members.map((m: any) => <option key={m.id} value={`m:${m.id}`}>{m.name}{m.member_type === "agent" ? " (AI)" : ""}</option>)}</optgroup>
                <optgroup label={tr("routines.phong_truong_phong_dinh_tuyen")}>{departments.map((d: any) => <option key={d.id} value={`d:${d.id}`}>{d.name}</option>)}</optgroup>
              </select></Field>
            </FormRow>
            <Field label="Runbook" hint={tr("routines.viec_can_lam_moi_lan")}><textarea rows={3} value={form.runbook} onChange={set("runbook")} placeholder={tr("routines.vd_lay_don_moi_tu")}/></Field>
            <FormRow>
              <Field label={tr("routines.lich_cron_5_truong")} hint={tr("routines.vd_30_8_8_30")}><input value={form.cron} onChange={set("cron")} data-testid="rf-cron" placeholder="30 8 * * *" spellCheck={false}/></Field>
              <Field label={tr("routines.mui_gio")}><input value={form.timezone} onChange={set("timezone")} spellCheck={false}/></Field>
            </FormRow>
            <FormRow>
              <Field label={tr("routines.gio_lo_khi_he_thong")}><select value={form.catch_up} onChange={set("catch_up")}>
                <option value="skip_missed">{tr("routines.bo_ghi_la_bo_qua")}</option><option value="run_once">{tr("routines.chay_bu_1_lan")}</option></select></Field>
              <Field label={tr("routines.kieu")}><select value={form.mode} onChange={set("mode")}>
                <option value="create_task">{tr("routines.moi_lan_mot_viec_moi")}</option><option value="run_only">{tr("routines.chi_danh_thuc_viec_thuong")}</option></select></Field>
              <Field label={tr("routines.tu_dung_sau_n_loi")}><input type="number" min={1} value={form.max_consecutive_failures} onChange={e => setForm({...form, max_consecutive_failures: Number(e.target.value)})}/></Field>
            </FormRow>
            <label className="ui-check"><input type="checkbox" checked={form.webhook} onChange={set("webhook")}/> {tr("routines.them_webhook_de_he_thong")}</label>
            <Button type="submit" variant="primary" disabled={!form.name || !form.target} data-testid="rf-submit">{tr("routines.tao_routine")}</Button>
          </form>
        </Panel>
      </div>
    </div>
  </PageFrame>;
}
