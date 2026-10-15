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
