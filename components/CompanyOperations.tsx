"use client";
// M2c — vận hành công ty trong Đội ngũ: Quy trình (D4). Mỗi bước của một lần chạy là một việc
// thường trên bảng việc (giao người ngồi chức danh, chặn nối tiếp, duyệt theo ma trận) — giao diện
// nói rõ điều đó và đo thời gian chu trình theo bước / lần chạy.
import {useEffect, useState} from "react";
import Link from "next/link";
import {apiOps} from "../lib/api";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {t as tr, type Key} from "../lib/i18n";
import {actLabel} from "./CompanyFoundation";

export function useLoad<T>(fn: () => Promise<T>, deps: any[]) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState<unknown>(null);
  const reload = () => fn().then(d => { setData(d); setError(null); }).catch(setError);
  useEffect(() => { setData(null); reload(); /* eslint-disable-next-line */ }, deps);
  return {data, error, reload, setError};
}
export const mins = (m: number | null | undefined) => m == null ? "—"
  : m < 60 ? tr("ops.min_n", {p0: Math.round(m * 10) / 10}) : tr("ops.hour_n", {p0: Math.round(m / 6) / 10});
const ACTIONS = ["", "spend", "refund", "external_message", "contract", "data_export", "data_delete", "exec"];
const STEP_STATUS: Record<string, string> = {waiting: "", active: "is-wait", done: "is-ok", cancelled: "is-risk"};

// ===================================================================== Quy trình (D4)

export function ProcessesTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiOps.processes(companyId), [companyId]);
  const [edit, setEdit] = useState<any>(null), [busy, setBusy] = useState(false);
  const [runFor, setRunFor] = useState<any>(null), [open, setOpen] = useState<Record<number, any>>({});
  const [tpl, setTpl] = useState("shop");
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="proc-error"/>;
  if (!data) return <SkeletonRows n={4} h={60}/>;
  const d: any = data;
  async function run(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await reload(); return r; }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function toggle(p: any) {
    if (open[p.id]) { const n = {...open}; delete n[p.id]; setOpen(n); return; }
    try { const r = await apiOps.instances(p.id); setOpen({...open, [p.id]: r.items}); } catch (e) { setError(e); }
  }
  const groups = d.categories.filter((c: any) => d.items.some((p: any) => p.category === c.key));
  const catName = (k: string) => tr(`ops.apqc_${k}` as Key);
  return <section className="ui-section" data-testid="processes">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("ops.proc_explain")}</p>
    <div className="ui-toolbar">
      <div className="org-stats"><span><b>{d.items.length}</b> {tr("ops.processes")}</span>
        <span><b>{d.items.reduce((a: number, p: any) => a + (p.stats?.running || 0), 0)}</b> {tr("ops.running")}</span>
        <span><b>{d.items.reduce((a: number, p: any) => a + (p.stats?.done || 0), 0)}</b> {tr("ops.done_runs")}</span></div>
      <span className="ui-grow"/>
      {can && <label className="tmInline">{tr("ops.template")}<select value={tpl} onChange={e => setTpl(e.target.value)} data-testid="proc-tpl">
        {d.templates.map((k: string) => <option key={k} value={k}>{tr(`ops.tpl_${k}` as Key)}</option>)}</select>
        <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="proc-seed"
          onClick={() => run(() => apiOps.seedProcesses({company_id: companyId ?? d.company_id, template: tpl}),
            (r: any) => tr("ops.seeded", {p0: r.created.length, p1: r.skipped.length}))}>{tr("ops.seed")}</button></label>}
      {can && <button className="ui-btn is-primary is-sm" onClick={() => setEdit({name: "", category: "6", description: "", owner_position_id: null, steps: [{name: ""}]})}
        data-testid="proc-new">{tr("ops.new_process")}</button>}
    </div>
    {edit && <ProcessForm d={d} edit={edit} busy={busy} onCancel={() => setEdit(null)} onSave={async (body: any) => {
      const r = await run(() => edit.id ? apiOps.updateProcess(edit.id, body) : apiOps.createProcess({...body, company_id: companyId ?? d.company_id}), tr("ops.saved"));
      if (r) setEdit(null);
    }}/>}
    {runFor && <RunForm p={runFor} busy={busy} onCancel={() => setRunFor(null)} onRun={async (body: any) => {
      const r = await run(() => apiOps.startProcess(runFor.id, body), (x: any) => tr("ops.started", {p0: x.id, p1: x.steps.length}));
      if (r) { const id = runFor.id; setRunFor(null); apiOps.instances(id).then(x => setOpen(o => ({...o, [id]: x.items}))).catch(setError); }
    }}/>}
    {!d.items.length ? <EmptyState mood="chao" title={tr("ops.proc_empty")} testId="proc-empty">{tr("ops.proc_empty_hint")}</EmptyState>
      : groups.map((c: any) => <div key={c.key} className="ops-group">
        <h3 className="ops-cat"><span className="ui-pill is-info">APQC {c.key}</span> {catName(c.key)}</h3>
        <div className="tmDepts">{d.items.filter((p: any) => p.category === c.key).map((p: any) =>
          <section key={p.id} className="ui-panel tm-card" data-testid={`proc-${p.id}`}>
            <div className="tm-card-head"><div><b>{p.name}</b>
              <span>{tr("ops.owner")}: {p.owner_position || tr("ops.no_owner")} · {tr("ops.expected_total")} {mins(p.expected_minutes)}</span></div>
              {p.stats?.running ? <span className="ui-pill is-wait">{tr("ops.n_running", {p0: p.stats.running})}</span> : null}</div>
            {p.description && <small className="tmGuide">{p.description}</small>}
            <ol className="ops-steps">{p.steps.map((s: any) => <li key={s.id}>
              <b>{s.name}</b> <span className="ops-meta">{s.position || tr("ops.no_position")} · {mins(s.expected_minutes)}
                {s.avg_minutes != null ? ` · ${tr("ops.avg")} ${mins(s.avg_minutes)}` : ""}</span>
              {s.action_type && <span className="ui-pill is-mid" title={tr("ops.action_hint")}>{actLabel(s.action_type)}</span>}
              {s.sop && <span className="ops-sop">📄 {s.sop}</span>}
            </li>)}</ol>
            {p.stats && <div className="org-stats ops-kpi" data-testid={`proc-stats-${p.id}`}>
              <span><b>{p.stats.instances}</b> {tr("ops.runs")}</span>
              <span><b>{mins(p.stats.avg_cycle_minutes)}</b> {tr("ops.avg_cycle")}</span>
              {p.stats.late_steps ? <span className="is-warn"><b>{p.stats.late_steps}</b> {tr("ops.late_steps")}</span> : null}</div>}
            {p.issues.length > 0 && <ul className="ops-issues">{p.issues.map((x: string, i: number) => <li key={i}>⚠ {x}</li>)}</ul>}
            <div className="tmRow">
              <button className="ui-btn is-primary is-sm" disabled={busy || !p.steps.length} onClick={() => setRunFor(p)} data-testid={`proc-run-${p.id}`}>{tr("ops.run")}</button>
              <button className="ui-btn is-ghost is-sm" onClick={() => toggle(p)} data-testid={`proc-inst-${p.id}`}>{open[p.id] ? tr("ops.hide_runs") : tr("ops.show_runs")}</button>
              {can && <button className="ui-btn is-ghost is-sm" onClick={() => setEdit({...p, steps: p.steps.map((s: any) => ({...s}))})}>{tr("ops.edit")}</button>}
              {can && !p.stats?.running && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiOps.archiveProcess(p.id), tr("ops.archived"))}>{tr("ops.archive")}</button>}
            </div>
            {open[p.id] && <Instances items={open[p.id]} can={can} busy={busy}
              onCancel={(id: number) => run(() => apiOps.cancelInstance(id), tr("ops.cancelled"))
                .then(() => apiOps.instances(p.id)).then(x => setOpen(o => ({...o, [p.id]: x.items}))).catch(setError)}/>}
          </section>)}</div>
      </div>)}
  </section>;
}

function Instances({items, can, busy, onCancel}: any) {
  if (!items.length) return <small className="tmGuide">{tr("ops.no_runs")}</small>;
  return <div className="ops-inst">{items.map((i: any) => <details key={i.id} open={i.status === "running"} data-testid={`inst-${i.id}`}>
    <summary><b>#{i.id} {i.title}</b> <span className={"ui-pill " + (i.status === "done" ? "is-ok" : i.status === "running" ? "is-wait" : "is-risk")}>{tr(`ops.st_${i.status}` as Key)}</span>
      {" "}{i.status === "done" ? tr("ops.cycle", {p0: mins(i.cycle_minutes)}) : tr("ops.elapsed", {p0: mins(i.elapsed_minutes)})}
      {i.amount_usd != null && ` · $${i.amount_usd}`}</summary>
    <table className="ui-table"><tbody>{i.steps.map((s: any) => <tr key={s.id}>
      <td>{s.seq}. {s.task_id ? <Link href={`/app/tasks/${s.task_id}`}>{s.name}</Link> : s.name}{s.note && <div><small>{s.note}</small></div>}</td>
      <td>{s.assignee || "—"}{s.approval_required && <div><small>{tr("ops.approval_by", {p0: s.approver || "?", p1: s.authority_rule_id || "?"})}</small></div>}</td>
      <td><span className={"ui-pill " + (STEP_STATUS[s.status] || "")}>{tr(`ops.ss_${s.status}` as Key)}</span>{s.late && <span className="ui-pill is-risk">{tr("ops.late")}</span>}</td>
      <td style={{textAlign: "right"}}>{s.cycle_minutes != null ? mins(s.cycle_minutes) : s.expected_minutes ? `≤ ${mins(s.expected_minutes)}` : ""}</td>
    </tr>)}</tbody></table>
    {can && i.status === "running" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => onCancel(i.id)}>{tr("ops.cancel_run")}</button>}
  </details>)}</div>;
}

function RunForm({p, busy, onCancel, onRun}: any) {
  const [title, setTitle] = useState(""), [amount, setAmount] = useState(""), [note, setNote] = useState("");
  const needsMoney = p.steps.some((s: any) => ["spend", "refund", "contract"].includes(s.action_type));
  return <section className="ui-panel tm-card cf-edit" data-testid="proc-run-form">
    <div className="tm-card-head"><div><b>{tr("ops.run_title", {p0: p.name})}</b><span>{tr("ops.run_desc", {p0: p.steps.length})}</span></div></div>
    <div className="ui-form cf-form">
      <FormRow>
        <Field label={tr("ops.run_name")} hint={tr("ops.run_name_hint")}><input value={title} onChange={e => setTitle(e.target.value)} data-testid="run-title"/></Field>
        {needsMoney && <Field label={tr("ops.amount_usd")} hint={tr("ops.amount_hint")}><input value={amount} inputMode="decimal" onChange={e => setAmount(e.target.value)} data-testid="run-amount"/></Field>}
      </FormRow>
      <Field label={tr("ops.run_note")}><textarea rows={2} value={note} onChange={e => setNote(e.target.value)}/></Field>
      <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} data-testid="run-go"
        onClick={() => onRun({title, amount_usd: amount === "" ? null : Number(amount), input: note ? {ghi_chu: note} : null})}>{tr("ops.run")}</button>
        <button className="ui-btn is-ghost" onClick={onCancel}>{tr("ops.cancel")}</button></div>
    </div>
  </section>;
}

function ProcessForm({d, edit, busy, onCancel, onSave}: any) {
  const [f, setF] = useState<any>(edit);
  const set = (k: string, v: any) => setF({...f, [k]: v});
  const setStep = (i: number, k: string, v: any) => set("steps", f.steps.map((s: any, j: number) => j === i ? {...s, [k]: v} : s));
  const move = (i: number, dir: number) => { const s = [...f.steps]; const j = i + dir; if (j < 0 || j >= s.length) return; [s[i], s[j]] = [s[j], s[i]]; set("steps", s); };
  const num = (v: any) => v === "" || v == null ? null : Number(v);
  return <section className="ui-panel tm-card cf-edit" data-testid="proc-form">
    <div className="tm-card-head"><div><b>{f.id ? tr("ops.edit_process") : tr("ops.new_process")}</b><span>{tr("ops.form_note")}</span></div></div>
    <div className="ui-form cf-form">
      <FormRow>
        <Field label={tr("ops.name")}><input value={f.name} onChange={e => set("name", e.target.value)} data-testid="pf-name"/></Field>
        <Field label={tr("ops.category")}><select value={f.category} onChange={e => set("category", e.target.value)} data-testid="pf-cat">
          {d.categories.map((c: any) => <option key={c.key} value={c.key}>{c.key}. {tr(`ops.apqc_${c.key}` as Key)}</option>)}</select></Field>
        <Field label={tr("ops.owner")}><select value={f.owner_position_id ?? ""} onChange={e => set("owner_position_id", num(e.target.value))} data-testid="pf-owner">
          <option value="">{tr("ops.choose")}</option>{d.positions.map((p: any) => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
      </FormRow>
      <Field label={tr("ops.description")}><textarea rows={2} value={f.description || ""} onChange={e => set("description", e.target.value)}/></Field>
      <div className="ui-field"><span className="ui-field-label">{tr("ops.steps")}</span>
        {f.steps.map((s: any, i: number) => <div key={i} className="ops-step-edit" data-testid={`pf-step-${i}`}>
          <span className="ops-seq">{i + 1}</span>
          <input placeholder={tr("ops.step_name")} value={s.name} onChange={e => setStep(i, "name", e.target.value)}/>
          <select value={s.position_id ?? ""} onChange={e => setStep(i, "position_id", num(e.target.value))} aria-label={tr("ops.position")}>
            <option value="">{tr("ops.position")}…</option>{d.positions.map((p: any) => <option key={p.id} value={p.id}>{p.title}</option>)}</select>
          <input className="ops-min" placeholder={tr("ops.minutes")} inputMode="numeric" value={s.expected_minutes ?? ""} onChange={e => setStep(i, "expected_minutes", num(e.target.value))}/>
          <select value={s.action_type || ""} onChange={e => setStep(i, "action_type", e.target.value)} aria-label={tr("ops.approval_type")}>
            {ACTIONS.map(a => <option key={a} value={a}>{a ? actLabel(a) : tr("ops.no_approval")}</option>)}</select>
          <select value={s.sop_id ?? ""} onChange={e => setStep(i, "sop_id", num(e.target.value))} aria-label="SOP">
            <option value="">SOP…</option>{d.sops.map((x: any) => <option key={x.id} value={x.id}>{x.title}</option>)}</select>
          <button className="ui-btn is-ghost is-sm" onClick={() => move(i, -1)} aria-label="↑">↑</button>
          <button className="ui-btn is-ghost is-sm" onClick={() => move(i, 1)} aria-label="↓">↓</button>
          <button className="ui-btn is-ghost is-sm" onClick={() => set("steps", f.steps.filter((_: any, j: number) => j !== i))} aria-label={tr("ops.remove")}>✕</button>
          <textarea rows={1} placeholder={tr("ops.instructions")} value={s.instructions || ""} onChange={e => setStep(i, "instructions", e.target.value)}/>
        </div>)}
        <button className="ui-btn is-ghost is-sm" onClick={() => set("steps", [...f.steps, {name: ""}])} data-testid="pf-add-step">{tr("ops.add_step")}</button>
      </div>
      <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} data-testid="pf-save" onClick={() => onSave({
        name: f.name, category: f.category, description: f.description || "", owner_position_id: f.owner_position_id ?? null,
        steps: f.steps.filter((s: any) => (s.name || "").trim()).map((s: any) => ({id: s.id, name: s.name, position_id: s.position_id ?? null,
          sop_id: s.sop_id ?? null, expected_minutes: s.expected_minutes ?? null, action_type: s.action_type || "", risk: s.risk || "",
          instructions: s.instructions || ""}))})}>{tr("ops.save")}</button>
        <button className="ui-btn is-ghost" onClick={onCancel}>{tr("ops.cancel")}</button></div>
    </div>
  </section>;
}

// ===================================================================== KPI chia tầng (D5)

const HEALTH: Record<string, string> = {on_track: "is-ok", at_risk: "is-wait", off_track: "is-risk", no_data: ""};
const fmt = (v: number | null | undefined, unit = "") => v == null ? "—" : `${Math.round(v * 100) / 100}${unit ? " " + unit : ""}`;

function Bar({p}: {p: number | null | undefined}) {
  if (p == null) return <span className="ops-bar is-empty"/>;
  return <span className="ops-bar" title={`${p}%`}><i style={{width: `${Math.min(100, p)}%`}} className={p >= 90 ? "is-ok" : p >= 60 ? "is-wait" : "is-risk"}/></span>;
}

export function KpiTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiOps.kpis(companyId), [companyId]);
  const [edit, setEdit] = useState<any>(null), [busy, setBusy] = useState(false), [rec, setRec] = useState<any>(null);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="kpi-error"/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  async function run(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await reload(); return r; }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const rows: any[] = [];
  const walk = (ns: any[], depth: number) => ns.forEach(n => { rows.push({...n, depth}); walk(n.children || [], depth + 1); });
  walk(d.tree, 0);
  const s = d.summary;
  return <section className="ui-section" data-testid="kpis">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("ops.kpi_explain")}</p>
    <div className="ui-toolbar">
      <div className="org-stats" data-testid="kpi-summary"><span><b>{s.company_progress == null ? "—" : s.company_progress + "%"}</b> {tr("ops.company_progress")}</span>
        <span><b>{s.kpis}</b> KPI</span><span className="is-ok"><b>{s.on_track}</b> {tr("ops.h_on_track")}</span>
        <span className="is-warn"><b>{s.at_risk}</b> {tr("ops.h_at_risk")}</span><span className="is-warn"><b>{s.off_track}</b> {tr("ops.h_off_track")}</span></div>
      <span className="ui-grow"/>
      {can && <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="kpi-sync"
        onClick={() => run(() => apiOps.syncKpis(companyId ?? d.company_id), (r: any) => tr("ops.kpi_synced", {p0: r.created, p1: r.updated}))}>{tr("ops.kpi_sync")}</button>}
      {can && <button className="ui-btn is-primary is-sm" data-testid="kpi-new" onClick={() => setEdit({level: "company", name: "", metric: "manual", period: "month", weight: 1})}>{tr("ops.new_kpi")}</button>}
    </div>
    {edit && <KpiForm d={d} edit={edit} busy={busy} onCancel={() => setEdit(null)} onSave={async (body: any) => {
      const r = await run(() => edit.id ? apiOps.updateKpi(edit.id, body) : apiOps.createKpi({...body, company_id: companyId ?? d.company_id}), tr("ops.kpi_saved"));
      if (r) setEdit(null);
    }}/>}
    {rec && <section className="ui-panel tm-card cf-edit" data-testid="kpi-record">
      <div className="tm-card-head"><div><b>{tr("ops.record_title", {p0: rec.name})}</b><span>{tr("ops.record_desc", {p0: rec.period_key})}</span></div></div>
      <div className="tmRow"><input inputMode="decimal" value={rec.v ?? ""} onChange={e => setRec({...rec, v: e.target.value})} placeholder={rec.unit} data-testid="kpi-record-value"/>
        <input value={rec.note ?? ""} onChange={e => setRec({...rec, note: e.target.value})} placeholder={tr("ops.note")}/>
        <button className="ui-btn is-primary is-sm" disabled={busy || rec.v === undefined || rec.v === ""} data-testid="kpi-record-save"
          onClick={async () => { const r = await run(() => apiOps.recordKpi(rec.id, {value: Number(rec.v), note: rec.note || ""}), tr("ops.recorded")); if (r) setRec(null); }}>{tr("ops.save")}</button>
        <button className="ui-btn is-ghost is-sm" onClick={() => setRec(null)}>{tr("ops.cancel")}</button></div>
    </section>}
    {!rows.length ? <EmptyState mood="chao" title={tr("ops.kpi_empty")} testId="kpi-empty">{tr("ops.kpi_empty_hint")}</EmptyState>
      : <div className="ui-panel"><table className="ui-table ops-kpi-table"><thead><tr>
        <th>KPI</th><th>{tr("ops.k_owner")}</th><th>{tr("ops.k_source")}</th><th style={{textAlign: "right"}}>{tr("ops.k_target")}</th>
        <th style={{textAlign: "right"}}>{tr("ops.k_actual")}</th><th>{tr("ops.k_progress")}</th><th/></tr></thead>
        <tbody>{rows.map(r => <tr key={r.id} data-testid={`kpi-${r.id}`}>
          <td style={{paddingLeft: 8 + r.depth * 18}}><span className="ui-pill is-info ops-lv">{tr(`ops.lv_${r.level}` as Key)}</span> <b>{r.name}</b>
            {r.goal && <div><small>🎯 {r.goal.title} ({r.goal.progress}%)</small></div>}</td>
          <td>{r.owner}</td>
          <td><small>{tr(`ops.m_${r.metric}` as Key)}{r.value_source === "manual" && r.metric !== "manual" ? ` · ${tr("ops.manual_override")}` : ""}</small></td>
          <td style={{textAlign: "right"}}>{r.direction === "down" ? "≤ " : ""}{fmt(r.target, r.unit)}</td>
          <td style={{textAlign: "right"}}><b>{fmt(r.value, r.unit)}</b></td>
          <td><Bar p={r.progress}/> <span className={"ui-pill " + HEALTH[r.health]}>{r.progress == null ? tr("ops.h_no_data") : r.progress + "%"}</span>
            {r.rollup != null && <div><small>{tr("ops.rollup", {p0: r.rollup})}</small></div>}</td>
          <td style={{textAlign: "right", whiteSpace: "nowrap"}}>
            <button className="ui-btn is-ghost is-sm" onClick={() => setRec({...r, v: ""})} data-testid={`kpi-rec-${r.id}`}>{tr("ops.record")}</button>
            {can && <button className="ui-btn is-ghost is-sm" onClick={() => setEdit({...r})}>{tr("ops.edit")}</button>}
            {can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiOps.deleteKpi(r.id), tr("ops.kpi_deleted"))}>✕</button>}
          </td></tr>)}</tbody></table></div>}
  </section>;
}

function KpiForm({d, edit, busy, onCancel, onSave}: any) {
  const [f, setF] = useState<any>(edit);
  const set = (k: string, v: any) => setF({...f, [k]: v});
  const num = (v: any) => v === "" || v == null ? null : Number(v);
  const procMetric = ["cycle_time_minutes", "on_time_rate", "process_runs_done"].includes(f.metric);
  return <section className="ui-panel tm-card cf-edit" data-testid="kpi-form">
    <div className="tm-card-head"><div><b>{f.id ? tr("ops.edit_kpi") : tr("ops.new_kpi")}</b><span>{tr("ops.kpi_form_note")}</span></div></div>
    <div className="ui-form cf-form">
      <FormRow>
        <Field label={tr("ops.k_name")}><input value={f.name} onChange={e => set("name", e.target.value)} data-testid="kf-name"/></Field>
        <Field label={tr("ops.k_level")}><select value={f.level} onChange={e => set("level", e.target.value)} data-testid="kf-level">
          {["company", "department", "position", "seat"].map(l => <option key={l} value={l}>{tr(`ops.lv_${l}` as Key)}</option>)}</select></Field>
        {f.level === "department" && <Field label={tr("ops.k_dept")}><select value={f.department_id ?? ""} onChange={e => set("department_id", num(e.target.value))}>
          <option value="">{tr("ops.choose")}</option>{d.departments.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>}
        {f.level === "position" && <Field label={tr("ops.position")}><select value={f.position_id ?? ""} onChange={e => set("position_id", num(e.target.value))}>
          <option value="">{tr("ops.choose")}</option>{d.positions.map((x: any) => <option key={x.id} value={x.id}>{x.title}</option>)}</select></Field>}
        {f.level === "seat" && <Field label={tr("ops.k_seat")}><select value={f.member_id ?? ""} onChange={e => set("member_id", num(e.target.value))}>
          <option value="">{tr("ops.choose")}</option>{d.members.map((x: any) => <option key={x.id} value={x.id}>{x.name}{x.type === "agent" ? " (agent)" : ""}</option>)}</select></Field>}
      </FormRow>
      <FormRow>
        <Field label={tr("ops.k_source")}><select value={f.metric} onChange={e => set("metric", e.target.value)} data-testid="kf-metric">
          {d.metrics.map((m: any) => <option key={m.key} value={m.key}>{tr(`ops.m_${m.key}` as Key)}</option>)}</select></Field>
        <Field label={tr("ops.k_target")}><input inputMode="decimal" value={f.target ?? ""} onChange={e => set("target", num(e.target.value))} data-testid="kf-target"/></Field>
        <Field label={tr("ops.k_unit")}><input value={f.unit ?? ""} onChange={e => set("unit", e.target.value)}/></Field>
        <Field label={tr("ops.k_period")}><select value={f.period} onChange={e => set("period", e.target.value)}>
          {["week", "month", "quarter"].map(p => <option key={p} value={p}>{tr(`ops.p_${p}` as Key)}</option>)}</select></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("ops.k_parent")}><select value={f.parent_id ?? ""} onChange={e => set("parent_id", num(e.target.value))}>
          <option value="">—</option>{d.items.filter((x: any) => x.id !== f.id).map((x: any) => <option key={x.id} value={x.id}>{x.name} · {x.owner}</option>)}</select></Field>
        <Field label={tr("ops.k_goal")}><select value={f.goal?.id ?? f.goal_id ?? ""} onChange={e => set("goal_id", num(e.target.value))}>
          <option value="">—</option>{d.goals.map((g: any) => <option key={g.id} value={g.id}>{g.title}</option>)}</select></Field>
        {procMetric && <Field label={tr("ops.k_process")}><select value={f.process_id ?? ""} onChange={e => set("process_id", num(e.target.value))}>
          <option value="">{tr("ops.all_processes")}</option>{d.processes.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>}
        <Field label={tr("ops.k_weight")}><input inputMode="decimal" value={f.weight ?? 1} onChange={e => set("weight", num(e.target.value))}/></Field>
      </FormRow>
      <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} data-testid="kf-save" onClick={() => onSave({
        name: f.name, level: f.level, department_id: f.level === "department" ? f.department_id ?? null : null,
        position_id: f.level === "position" ? f.position_id ?? null : (f.level === "seat" ? f.position_id ?? null : null),
        member_id: f.level === "seat" ? f.member_id ?? null : null, metric: f.metric, target: f.target ?? null, unit: f.unit || "",
        period: f.period, parent_id: f.parent_id ?? null, goal_id: f.goal?.id ?? f.goal_id ?? null,
        process_id: procMetric ? f.process_id ?? null : null, weight: f.weight || 1})}>{tr("ops.save")}</button>
        <button className="ui-btn is-ghost" onClick={onCancel}>{tr("ops.cancel")}</button></div>
    </div>
  </section>;
}

// ===================================================================== Nhịp vận hành (D6)

const DOW = [0, 1, 2, 3, 4, 5, 6];

export function RhythmTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiOps.rhythm(companyId), [companyId]);
  const [f, setF] = useState<any>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  useEffect(() => { if (data) setF({...(data as any).config}); }, [data]);
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="rh-error"/>;
  if (!data || !f) return <SkeletonRows n={4} h={44}/>;
  const d: any = data;
  const set = (k: string, v: any) => setF({...f, [k]: v});
  async function run(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await reload(); return r; }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const cid = companyId ?? d.company_id;
  return <section className="ui-section" data-testid="rhythm">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("ops.rh_explain")}</p>
    <div className="ui-grid is-2">
      <section className="ui-panel tm-card">
        <div className="tm-card-head"><div><b>{tr("ops.rh_schedule")}</b><span>{f.enabled ? tr("ops.rh_on") : tr("ops.rh_off")}</span></div>
          <span className={"ui-pill " + (f.enabled ? "is-ok" : "")}>{f.enabled ? tr("ops.rh_auto") : tr("ops.rh_manual")}</span></div>
        <fieldset disabled={!can || busy} className="ui-form cf-form">
          <label className="tmInline"><input type="checkbox" checked={!!f.standup_enabled} onChange={e => set("standup_enabled", e.target.checked)} data-testid="rh-standup"/>
            {tr("ops.rh_standup_at")} <input className="ops-min" inputMode="numeric" value={f.standup_hour} onChange={e => set("standup_hour", Number(e.target.value) || 0)}/> {tr("ops.rh_hour")}</label>
          <label className="tmInline"><input type="checkbox" checked={!!f.weekly_enabled} onChange={e => set("weekly_enabled", e.target.checked)}/>
            {tr("ops.rh_weekly_on")} <select value={f.weekly_dow} onChange={e => set("weekly_dow", Number(e.target.value))}>
              {DOW.map(x => <option key={x} value={x}>{tr(`ops.dow_${x}` as Key)}</option>)}</select>
            <input className="ops-min" inputMode="numeric" value={f.weekly_hour} onChange={e => set("weekly_hour", Number(e.target.value) || 0)}/> {tr("ops.rh_hour")}</label>
          <label className="tmInline"><input type="checkbox" checked={!!f.per_department} onChange={e => set("per_department", e.target.checked)}/>{tr("ops.rh_per_dept")}</label>
          <label className="tmInline"><input type="checkbox" checked={!!f.agent_author} onChange={e => set("agent_author", e.target.checked)}/>{tr("ops.rh_agent")}</label>
          <small className="tmGuide">{tr("ops.rh_tz", {p0: f.timezone})}</small>
        </fieldset>
        {can && <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} data-testid="rh-save"
          onClick={() => run(() => apiOps.saveRhythm({company_id: cid, standup_enabled: f.standup_enabled, standup_hour: f.standup_hour,
            weekly_enabled: f.weekly_enabled, weekly_dow: f.weekly_dow, weekly_hour: f.weekly_hour, per_department: f.per_department,
            agent_author: f.agent_author}), tr("ops.saved_short"))}>{tr("ops.save")}</button></div>}
      </section>
      <section className="ui-panel tm-card">
        <div className="tm-card-head"><div><b>{tr("ops.rh_now")}</b><span>{tr("ops.rh_now_desc")}</span></div></div>
        {can ? <div className="tmRow">
          <button className="ui-btn is-ghost" disabled={busy} data-testid="rh-run-standup"
            onClick={() => run(() => apiOps.runRhythm({company_id: cid, kind: "standup", all_departments: true}),
              (r: any) => tr("ops.rh_sent", {p0: r.items.filter((x: any) => x.created).length}))}>{tr("ops.rh_run_standup")}</button>
          <button className="ui-btn is-ghost" disabled={busy} data-testid="rh-run-weekly"
            onClick={() => run(() => apiOps.runRhythm({company_id: cid, kind: "weekly", all_departments: true}),
              (r: any) => tr("ops.rh_sent", {p0: r.items.filter((x: any) => x.created).length}))}>{tr("ops.rh_run_weekly")}</button>
        </div> : <small>{tr("ops.need_manager")}</small>}
        {busy && <small className="tmGuide">{tr("ops.rh_busy")}</small>}
      </section>
    </div>
    <h3 className="ops-cat">{tr("ops.rh_recent")}</h3>
    {!d.reports.length ? <EmptyState mood="ngu" title={tr("ops.rh_empty")} testId="rh-empty">{tr("ops.rh_empty_hint")}</EmptyState>
      : <div className="ops-inst">{d.reports.map((r: any) => <details key={r.id} data-testid={`rh-${r.id}`}>
        <summary><b>{r.title}</b> <span className={"ui-pill " + (r.by_agent ? "is-info" : "")}>{r.by_agent ? tr("ops.rh_by_agent") : tr("ops.rh_by_system")}</span>
          {" "}<small>→ {r.recipients.join(", ") || "—"} · {new Date(r.created_at + "Z").toLocaleString()}</small></summary>
        <pre className="ibx-pre ops-report">{r.content}</pre>
        {r.author_note && <small className="tmGuide">{r.author_note}</small>}
        {r.by_agent && <details><summary><small>{tr("ops.rh_fallback")}</small></summary><pre className="ibx-pre ops-report">{r.fallback}</pre></details>}
      </details>)}</div>}
  </section>;
}
