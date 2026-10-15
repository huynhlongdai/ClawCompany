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
import {t as tr, type Key, intlLocale} from "../lib/i18n";
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
const STEP_STATUS: Record<string, string> = {waiting: "", active: "is-wait", done: "is-ok", skipped: "is-outline", cancelled: "is-risk"};
const COND_OPS = ["==", "!=", ">", ">=", "<", "<=", "empty", "not_empty"];
// v2: điều kiện của bước → câu đọc được ("Số tiền ≥ 50")
export function condText(c: any): string {
  if (!c) return "";
  const m = /^step(\d+)\.outcome$/.exec(c.field || "");
  const f = c.field === "amount_usd" ? tr("ops.cf_amount") : m ? tr("ops.cf_outcome", {p0: m[1]})
    : (c.field || "").startsWith("input.") ? tr("ops.cf_input", {p0: c.field.slice(6)}) : c.field;
  if (c.op === "empty") return tr("ops.cond_empty", {p0: f});
  if (c.op === "not_empty") return tr("ops.cond_not_empty", {p0: f});
  return `${f} ${c.op.replace(">=", "≥").replace("<=", "≤").replace("!=", "≠")} ${c.field === "amount_usd" ? "$" : ""}${c.value}`;
}
const linearDeps = (s: any) => JSON.stringify(s.depends_on || []) === JSON.stringify(s.seq > 1 ? [s.seq - 1] : []);

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
              {s.branch && <span className="ui-pill is-info">{tr("ops.branch")}: {s.branch}</span>}
              {!linearDeps(s) && <span className="ui-pill is-outline" data-testid={`proc-deps-${s.id}`}>{s.depends_on.length
                ? tr("ops.after_steps", {p0: s.depends_on.map((x: number) => "B" + x).join(", ")}) : tr("ops.at_start")}</span>}
              {s.condition && <span className="ui-pill is-wait" data-testid={`proc-cond-${s.id}`}>{tr("ops.only_if", {p0: condText(s.condition)})}</span>}
              {s.sop && <span className="ops-sop">📄 {s.sop}</span>}
            </li>)}</ol>
            {p.stats && <div className="org-stats ops-kpi" data-testid={`proc-stats-${p.id}`}>
              <span><b>{p.stats.instances}</b> {tr("ops.runs")}</span>
              <span><b>{mins(p.stats.avg_cycle_minutes)}</b> {tr("ops.avg_cycle")}</span>
              {p.stats.late_steps ? <span className="is-warn"><b>{p.stats.late_steps}</b> {tr("ops.late_steps")}</span> : null}</div>}
            {p.stats && (p.stats.paths?.length > 1 || p.stats.branches?.length > 0) && <div className="org-stats ops-kpi" data-testid={`proc-branches-${p.id}`}>
              {p.stats.paths.map((x: any) => <span key={"p" + x.path}>{x.path === "—" ? tr("ops.path_main") : tr("ops.path_via", {p0: x.path})}: <b>{mins(x.avg_cycle_minutes)}</b> ({x.instances})</span>)}
              {p.stats.branches.map((x: any) => <span key={"b" + x.branch}>{tr("ops.branch_time", {p0: x.branch})}: <b>{mins(x.avg_minutes)}</b></span>)}</div>}
            {p.issues.length > 0 && <ul className="ops-issues">{p.issues.map((x: string, i: number) => <li key={i}>⚠ {x}</li>)}</ul>}
            <div className="tmRow">
              <button className="ui-btn is-primary is-sm" disabled={busy || !p.steps.length} onClick={() => setRunFor(p)} data-testid={`proc-run-${p.id}`}>{tr("ops.run")}</button>
              <button className="ui-btn is-ghost is-sm" onClick={() => toggle(p)} data-testid={`proc-inst-${p.id}`}>{open[p.id] ? tr("ops.hide_runs") : tr("ops.show_runs")}</button>
              {can && <button className="ui-btn is-ghost is-sm" onClick={() => setEdit({...p, steps: p.steps.map((s: any) => ({...s}))})}>{tr("ops.edit")}</button>}
              {can && !p.stats?.running && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiOps.archiveProcess(p.id), tr("ops.archived"))}>{tr("ops.archive")}</button>}
            </div>
            {open[p.id] && <Instances items={open[p.id]} can={can} busy={busy}
              onOutcome={(id: number, v: string) => run(() => apiOps.stepOutcome(id, v), tr("ops.outcome_saved"))
                .then(() => apiOps.instances(p.id)).then(x => setOpen(o => ({...o, [p.id]: x.items}))).catch(setError)}
              onCancel={(id: number) => run(() => apiOps.cancelInstance(id), tr("ops.cancelled"))
                .then(() => apiOps.instances(p.id)).then(x => setOpen(o => ({...o, [p.id]: x.items}))).catch(setError)}/>}
          </section>)}</div>
      </div>)}
  </section>;
}

function Outcome({s, busy, onOutcome}: any) {
  const [v, setV] = useState(s.outcome || "");
  return <div className="tmRow ops-outcome"><input value={v} placeholder={tr("ops.outcome_ph")} onChange={e => setV(e.target.value)}
    aria-label={tr("ops.outcome")} data-testid={`outcome-${s.id}`}/>
    <button className="ui-btn is-ghost is-sm" disabled={busy || v === (s.outcome || "")} onClick={() => onOutcome(s.id, v)}>{tr("ops.outcome_save")}</button></div>;
}

function Instances({items, can, busy, onCancel, onOutcome}: any) {
  if (!items.length) return <small className="tmGuide">{tr("ops.no_runs")}</small>;
  return <div className="ops-inst">{items.map((i: any) => <details key={i.id} open={i.status === "running"} data-testid={`inst-${i.id}`}>
    <summary><b>#{i.id} {i.title}</b> <span className={"ui-pill " + (i.status === "done" ? "is-ok" : i.status === "running" ? "is-wait" : "is-risk")}>{tr(`ops.st_${i.status}` as Key)}</span>
      {" "}{i.status === "done" ? tr("ops.cycle", {p0: mins(i.cycle_minutes)}) : tr("ops.elapsed", {p0: mins(i.elapsed_minutes)})}
      {i.amount_usd != null && ` · $${i.amount_usd}`}</summary>
    <table className="ui-table"><tbody>{i.steps.map((s: any) => <tr key={s.id}>
      <td>{s.seq}. {s.task_id ? <Link href={`/app/tasks/${s.task_id}`}>{s.name}</Link> : s.name}
        {s.branch && <span className="ui-pill is-info">{s.branch}</span>}{s.note && <div><small>{s.note}</small></div>}
        {s.condition && <div><small>{tr("ops.only_if", {p0: condText(s.condition)})}</small></div>}
        {s.skip_reason && <div><small className="is-warn">{s.skip_reason}</small></div>}
        {s.outcome && s.status !== "active" && <div><small>{tr("ops.outcome")}: <b>{s.outcome}</b></small></div>}
        {i.status === "running" && s.status === "active" && onOutcome && <Outcome s={s} busy={busy} onOutcome={onOutcome}/>}</td>
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
  // depends_on trỏ theo số thứ tự bước → đổi chỗ / xoá bước thì đánh số lại, bỏ tham chiếu không còn hợp lệ
  const deps = (s: any, i: number) => s.depends_on ?? (i > 0 ? [i] : []);
  const renumber = (steps: any[], map: (n: number) => number | null) => steps.map((s: any, i: number) => {
    const d = deps(s, i).map(map).filter((n: number | null) => n != null && n >= 1 && n <= i) as number[];
    const c = s.condition; const m = c ? /^step(\d+)\.outcome$/.exec(c.field || "") : null;
    const nc = m ? (map(Number(m[1])) && (map(Number(m[1])) as number) <= i ? {...c, field: `step${map(Number(m[1]))}.outcome`} : null) : c;
    return {...s, depends_on: Array.from(new Set(d)).sort((a, b) => a - b), condition: nc};
  });
  const move = (i: number, dir: number) => {
    const j = i + dir; if (j < 0 || j >= f.steps.length) return;
    const s = f.steps.map((x: any, k: number) => ({...x, depends_on: deps(x, k)})); [s[i], s[j]] = [s[j], s[i]];
    set("steps", renumber(s, n => n === i + 1 ? j + 1 : n === j + 1 ? i + 1 : n));
  };
  const remove = (i: number) => {
    const s = f.steps.map((x: any, k: number) => ({...x, depends_on: deps(x, k)})).filter((_: any, k: number) => k !== i);
    set("steps", renumber(s, n => n === i + 1 ? null : n > i + 1 ? n - 1 : n));
  };
  const compact = () => {  // bỏ bước trống tên mà không làm lệch tham chiếu "chạy sau bước"
    let s = f.steps.map((x: any, k: number) => ({...x, depends_on: deps(x, k)}));
    for (let i = s.length - 1; i >= 0; i--) if (!(s[i].name || "").trim()) {
      s = renumber(s.filter((_: any, k: number) => k !== i), n => n === i + 1 ? null : n > i + 1 ? n - 1 : n);
    }
    return s;
  };
  const toggleDep = (i: number, n: number) => {
    const d = deps(f.steps[i], i); setStep(i, "depends_on", d.includes(n) ? d.filter((x: number) => x !== n) : [...d, n].sort((a, b) => a - b));
  };
  const setCond = (i: number, k: string, v: any) => {
    const c = {field: "", op: ">=", value: "", ...(f.steps[i].condition || {}), [k]: v};
    setStep(i, "condition", c.field ? c : null);
  };
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
          <button className="ui-btn is-ghost is-sm" onClick={() => remove(i)} aria-label={tr("ops.remove")}>✕</button>
          <textarea rows={1} placeholder={tr("ops.instructions")} value={s.instructions || ""} onChange={e => setStep(i, "instructions", e.target.value)}/>
          <div className="ops-flow" data-testid={`pf-flow-${i}`}>
            <span className="ops-flow-label">{tr("ops.runs_after")}</span>
            {i === 0 ? <small>{tr("ops.at_start")}</small> : <>{Array.from({length: i}, (_, k) => k + 1).map(n =>
              <button key={n} type="button" className="ui-chip" aria-pressed={deps(s, i).includes(n)} onClick={() => toggleDep(i, n)}
                data-testid={`pf-dep-${i}-${n}`}>B{n}</button>)}
              {!deps(s, i).length && <small>{tr("ops.at_start")}</small>}</>}
            <input className="ops-branch" placeholder={tr("ops.branch_ph")} value={s.branch || ""} onChange={e => setStep(i, "branch", e.target.value)}
              aria-label={tr("ops.branch")} data-testid={`pf-branch-${i}`}/>
            <select value={s.condition?.field?.startsWith("input.") ? "input." : s.condition?.field || ""} aria-label={tr("ops.condition")}
              data-testid={`pf-cond-field-${i}`}
              onChange={e => setCond(i, "field", e.target.value === "input." ? "input.ghi_chu" : e.target.value)}>
              <option value="">{tr("ops.cond_none")}</option>
              <option value="amount_usd">{tr("ops.cf_amount")}</option>
              <option value="input.">{tr("ops.cf_input_any")}</option>
              {Array.from({length: i}, (_, k) => k + 1).map(n => <option key={n} value={`step${n}.outcome`}>{tr("ops.cf_outcome", {p0: n})}</option>)}
            </select>
            {s.condition?.field?.startsWith("input.") && <input className="ops-branch" value={s.condition.field.slice(6)} aria-label={tr("ops.cf_input_key")}
              onChange={e => setCond(i, "field", "input." + e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))}/>}
            {s.condition && <><select value={s.condition.op} onChange={e => setCond(i, "op", e.target.value)} aria-label={tr("ops.cond_op")} data-testid={`pf-cond-op-${i}`}>
              {COND_OPS.map(o => <option key={o} value={o}>{tr(`ops.op_${o}` as Key)}</option>)}</select>
              {!["empty", "not_empty"].includes(s.condition.op) && <input className="ops-min" value={s.condition.value ?? ""} aria-label={tr("ops.cond_value")}
                data-testid={`pf-cond-val-${i}`} onChange={e => setCond(i, "value", e.target.value)}/>}</>}
          </div>
        </div>)}
        <small className="tmGuide">{tr("ops.flow_hint")}</small>
        <button className="ui-btn is-ghost is-sm" onClick={() => set("steps", [...f.steps, {name: ""}])} data-testid="pf-add-step">{tr("ops.add_step")}</button>
      </div>
      <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} data-testid="pf-save" onClick={() => onSave({
        name: f.name, category: f.category, description: f.description || "", owner_position_id: f.owner_position_id ?? null,
        steps: compact().map((s: any) => ({id: s.id, name: s.name, position_id: s.position_id ?? null,
          sop_id: s.sop_id ?? null, expected_minutes: s.expected_minutes ?? null, action_type: s.action_type || "", risk: s.risk || "",
          instructions: s.instructions || "", depends_on: s.depends_on, branch: s.branch || "",
          condition: s.condition && s.condition.field ? {...s.condition,
            value: [">", ">=", "<", "<="].includes(s.condition.op) ? Number(s.condition.value) : s.condition.value} : null}))})}>{tr("ops.save")}</button>
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

// M2d.2: đường xu hướng theo kỳ (số đã lưu ở kpi_snapshots). Màu theo sức khoẻ kỳ cuối, chấm = kỳ hiện tại.
export function Sparkline({hist, unit, testId}: {hist: any[]; unit: string; testId?: string}) {
  const pts = (hist || []).filter((h: any) => h.value != null);
  if (pts.length < 2) return <small className="ops-spark-empty" data-testid={testId}>{pts.length ? tr("ops.trend_one") : tr("ops.trend_none")}</small>;
  const W = 96, H = 26, vals = pts.map((h: any) => h.value as number);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const xy = pts.map((h: any, i: number) => [2 + i * (W - 4) / (pts.length - 1), H - 3 - ((h.value - lo) / span) * (H - 6)]);
  const last = pts[pts.length - 1];
  const tone = last.health === "on_track" ? "is-ok" : last.health === "at_risk" ? "is-wait" : last.health === "off_track" ? "is-risk" : "";
  const title = pts.map((h: any) => `${h.period_key}: ${fmt(h.value, unit)}${h.final ? "" : " (" + tr("ops.trend_running") + ")"}`).join("\n");
  return <svg className={"ops-spark " + tone} width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr("ops.trend")} data-testid={testId}>
    <title>{title}</title>
    <polyline fill="none" strokeWidth="1.6" points={xy.map(p => p.join(",")).join(" ")}/>
    <circle cx={xy[xy.length - 1][0]} cy={xy[xy.length - 1][1]} r="2.4"/>
  </svg>;
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
      {can && <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="kpi-snapshot" title={tr("ops.snapshot_hint")}
        onClick={() => run(() => apiOps.snapshotKpis({company_id: companyId ?? d.company_id, backfill: 5}),
          (r: any) => tr("ops.snapshot_done", {p0: r.snapshots, p1: r.backfilled}))}>{tr("ops.snapshot")}</button>}
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
        <th style={{textAlign: "right"}}>{tr("ops.k_actual")}</th><th>{tr("ops.k_progress")}</th><th>{tr("ops.trend")}</th><th/></tr></thead>
        <tbody>{rows.map(r => <tr key={r.id} data-testid={`kpi-${r.id}`}>
          <td style={{paddingLeft: 8 + r.depth * 18}}><span className="ui-pill is-info ops-lv">{tr(`ops.lv_${r.level}` as Key)}</span> <b>{r.name}</b>
            {r.goal && <div><small>🎯 {r.goal.title} ({r.goal.progress}%)</small></div>}</td>
          <td>{r.owner}</td>
          <td><small>{tr(`ops.m_${r.metric}` as Key)}{r.value_source === "manual" && r.metric !== "manual" ? ` · ${tr("ops.manual_override")}` : ""}</small></td>
          <td style={{textAlign: "right"}}>{r.direction === "down" ? "≤ " : ""}{fmt(r.target, r.unit)}</td>
          <td style={{textAlign: "right"}}><b>{fmt(r.value, r.unit)}</b></td>
          <td><Bar p={r.progress}/> <span className={"ui-pill " + HEALTH[r.health]}>{r.progress == null ? tr("ops.h_no_data") : r.progress + "%"}</span>
            {r.rollup != null && <div><small>{tr("ops.rollup", {p0: r.rollup})}</small></div>}</td>
          <td><Sparkline hist={r.history} unit={r.unit} testId={`kpi-trend-${r.id}`}/></td>
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
          {" "}<small>→ {r.recipients.join(", ") || "—"} · {new Date(r.created_at + "Z").toLocaleString(intlLocale())}</small></summary>
        <pre className="ibx-pre ops-report">{r.content}</pre>
        {r.author_note && <small className="tmGuide">{r.author_note}</small>}
        {r.by_agent && <details><summary><small>{tr("ops.rh_fallback")}</small></summary><pre className="ibx-pre ops-report">{r.fallback}</pre></details>}
      </details>)}</div>}
  </section>;
}

// ===================================================================== Lịch tuân thủ (D7)

const fdate = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(intlLocale());

// M2d.3: lịch nghỉ lễ theo năm — CHỈ để tính hạn pháp lý; agent làm mọi ngày.
function Holidays({d, isAdmin, busy, run}: any) {
  const years = Object.keys(d.holidays || {}).sort();
  const [y, setY] = useState(years[0] || ""), [add, setAdd] = useState<any>(null);
  const items: any[] = (d.holidays || {})[y] || [];
  return <section className="ui-panel tm-card" data-testid="cmp-holidays">
    <div className="tm-card-head"><div><b>{tr("ops.hol_title")}</b><span>{tr("ops.hol_desc")}</span></div>
      <div className="ui-seg">{years.map(k => <button key={k} aria-pressed={k === y} onClick={() => setY(k)} data-testid={`hol-year-${k}`}>{k}</button>)}</div></div>
    <small className="tmGuide">{d.weekend_note} {d.legal_rule_url && <a href={d.legal_rule_url} target="_blank" rel="noreferrer">{tr("ops.hol_source")}</a>}</small>
    <table className="ui-table"><tbody>{items.map((h: any) => <tr key={h.id} data-testid={`hol-${h.day}`}>
      <td style={{whiteSpace: "nowrap"}}><b>{fdate(h.day)}</b></td>
      <td>{h.name}{h.kind === "makeup_workday" && <span className="ui-pill is-info">{tr("ops.hol_makeup")}</span>}
        {h.status === "needs_confirmation" && <span className="ui-pill is-wait">{tr("ops.hol_unconfirmed")}</span>}
        {h.note && <div><small>{h.note}</small></div>}</td>
      <td>{h.source_url && <a href={h.source_url} target="_blank" rel="noreferrer"><small>{tr("ops.hol_source")}</small></a>}</td>
      <td style={{textAlign: "right", whiteSpace: "nowrap"}}>{isAdmin && h.status === "needs_confirmation" && <button className="ui-btn is-ghost is-sm" disabled={busy}
          onClick={() => run(() => apiOps.updateHoliday(h.id, {status: "official"}), (r: any) => tr("ops.hol_saved", {p0: r.legal_due_updated}))}>{tr("ops.hol_confirm")}</button>}
        {isAdmin && <button className="ui-btn is-ghost is-sm" disabled={busy} aria-label={tr("ops.remove")}
          onClick={() => run(() => apiOps.deleteHoliday(h.id), (r: any) => tr("ops.hol_saved", {p0: r.legal_due_updated}))}>✕</button>}</td>
    </tr>)}</tbody></table>
    {isAdmin && (add ? <div className="tmRow" data-testid="hol-add-form">
      <input type="date" value={add.day} onChange={e => setAdd({...add, day: e.target.value})} aria-label={tr("ops.hol_day")}/>
      <input value={add.name} placeholder={tr("ops.hol_name_ph")} onChange={e => setAdd({...add, name: e.target.value})}/>
      <select value={add.kind} onChange={e => setAdd({...add, kind: e.target.value})} aria-label={tr("ops.hol_kind")}>
        <option value="holiday">{tr("ops.hol_holiday")}</option><option value="makeup_workday">{tr("ops.hol_makeup")}</option></select>
      <button className="ui-btn is-primary is-sm" disabled={busy || !add.day || !add.name}
        onClick={async () => { const r = await run(() => apiOps.createHoliday(add), (x: any) => tr("ops.hol_saved", {p0: x.legal_due_updated})); if (r) setAdd(null); }}>{tr("ops.save")}</button>
      <button className="ui-btn is-ghost is-sm" onClick={() => setAdd(null)}>{tr("ops.cancel")}</button></div>
      : <button className="ui-btn is-ghost is-sm" onClick={() => setAdd({day: "", name: "", kind: "holiday", status: "official"})} data-testid="hol-add">{tr("ops.hol_add")}</button>)}
  </section>;
}

export function ComplianceTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiOps.compliance(companyId), [companyId]);
  const [f, setF] = useState<any>(null), [busy, setBusy] = useState(false), [lic, setLic] = useState<any>(null);
  const toast = useToast();
  const isAdmin = !!caps?.manage_roles || !!caps?.create_company;
  const can = !!caps?.invite || isAdmin;
  useEffect(() => { if (data) setF({...(data as any).settings}); }, [data]);
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="cmp-error"/>;
  if (!data || !f) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  const cid = companyId ?? d.company_id;
  const set = (k: string, v: any) => setF({...f, [k]: v});
  async function run(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await reload(); return r; }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const upcoming = d.deadlines.filter((x: any) => x.status !== "done");
  const done = d.deadlines.filter((x: any) => x.status === "done");
  const freq = (r: any) => tr(`ops.fq_${r.frequency}` as Key);
  return <section className="ui-section" data-testid="compliance">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <div className="ui-banner" data-testid="cmp-disclaimer">⚖ {tr("ops.cmp_disclaimer")}</div>
    <div className="ui-grid is-2">
      <section className="ui-panel tm-card">
        <div className="tm-card-head"><div><b>{tr("ops.cmp_settings")}</b>
          <span>{tr("ops.cmp_entity")}: {f.entity_type ? tr(`company.et_${f.entity_type}` as Key) : tr("ops.cmp_no_entity")}
            {" · "}<Link href={`/app/team?tab=profile${cid ? `&company=${cid}` : ""}`}>{tr("ops.cmp_edit_profile")}</Link></span></div></div>
        <fieldset disabled={!isAdmin || busy} className="ui-form cf-form">
          <FormRow>
            <Field label={tr("ops.cmp_vat")}><select value={f.vat_period} onChange={e => set("vat_period", e.target.value)} data-testid="cmp-vat">
              <option value="monthly">{tr("ops.fq_monthly")}</option><option value="quarterly">{tr("ops.fq_quarterly")}</option></select></Field>
            <Field label={tr("ops.cmp_pit")}><select value={f.pit_period} onChange={e => set("pit_period", e.target.value)}>
              <option value="monthly">{tr("ops.fq_monthly")}</option><option value="quarterly">{tr("ops.fq_quarterly")}</option></select></Field>
          </FormRow>
          <label className="tmInline"><input type="checkbox" checked={!!f.has_employees} onChange={e => set("has_employees", e.target.checked)} data-testid="cmp-emp"/>{tr("ops.cmp_employees")}</label>
          <Field label={tr("ops.cmp_accountant")} hint={tr("ops.cmp_accountant_hint", {p0: d.assignee})}>
            <select value={f.accounting_position_id ?? ""} onChange={e => set("accounting_position_id", e.target.value ? Number(e.target.value) : null)}>
              <option value="">{tr("ops.cmp_auto")}</option>{d.positions.map((p: any) => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
        </fieldset>
        {!isAdmin && <small>{tr("ops.cmp_need_admin")}</small>}
        <div className="tmRow">
          {isAdmin && <button className="ui-btn is-primary" disabled={busy} data-testid="cmp-save"
            onClick={() => run(() => apiOps.saveCompliance({company_id: cid, vat_period: f.vat_period, pit_period: f.pit_period,
              has_employees: f.has_employees, accounting_position_id: f.accounting_position_id ?? null}), tr("ops.saved_short"))}>{tr("ops.save")}</button>}
          {isAdmin && !d.rules.length && <button className="ui-btn is-ghost" disabled={busy} data-testid="cmp-seed"
            onClick={() => run(() => apiOps.seedCompliance({company_id: cid}), (r: any) => tr("ops.cmp_seeded", {p0: r.created}))}>{tr("ops.cmp_seed")}</button>}
          {can && d.rules.length > 0 && <button className="ui-btn is-ghost" disabled={busy} data-testid="cmp-generate"
            onClick={() => run(() => apiOps.generateCompliance(cid), (r: any) => tr("ops.cmp_generated", {p0: r.created, p1: r.reminded}))}>{tr("ops.cmp_generate")}</button>}
        </div>
      </section>
      <section className="ui-panel tm-card">
        <div className="tm-card-head"><div><b>{tr("ops.cmp_upcoming")}</b><span>{tr("ops.cmp_upcoming_desc", {p0: upcoming.length})}</span></div></div>
        {!upcoming.length ? <EmptyState compact mood="ngu" title={tr("ops.cmp_empty")} testId="cmp-empty">{tr("ops.cmp_empty_hint")}</EmptyState>
          : <table className="ui-table" data-testid="cmp-deadlines"><tbody>{upcoming.map((x: any) => <tr key={x.id} data-testid={`cmp-d-${x.id}`}>
            <td><b>{fdate(x.due_date)}</b>{x.shifted && <div data-testid={`cmp-legal-${x.id}`}><small title={d.weekend_note}>{tr("ops.cmp_legal_due", {p0: fdate(x.legal_due_date), p1: x.legal_shift_reason})}</small></div>}</td>
            <td>{x.name} · <small>{x.period_label}</small>{x.needs_review && <span className="ui-pill is-wait" title={tr("ops.cmp_review_hint")}>{tr("ops.cmp_review")}</span>}
              <div><small>{x.assignee ? tr("ops.cmp_assigned", {p0: x.assignee}) : ""}{x.task_id ? <> · <Link href={`/app/tasks/${x.task_id}`}>{tr("ops.cmp_task")}</Link></> : ""}</small></div></td>
            <td><span className={"ui-pill " + (x.overdue ? "is-risk" : x.days_left <= 7 ? "is-wait" : "")}>{x.overdue ? tr("ops.cmp_overdue", {p0: -x.days_left}) : tr("ops.cmp_days", {p0: x.days_left})}</span></td>
            <td style={{textAlign: "right"}}>{can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiOps.complianceDone(x.id), tr("ops.cmp_marked"))}>{tr("ops.cmp_done")}</button>}</td>
          </tr>)}</tbody></table>}
        {done.length > 0 && <small className="tmGuide">{tr("ops.cmp_done_n", {p0: done.length})}</small>}
      </section>
    </div>
    <Holidays d={d} isAdmin={isAdmin} busy={busy} run={run}/>
    <h3 className="ops-cat">{tr("ops.cmp_rules")} {can && <button className="ui-btn is-ghost is-sm" onClick={() => setLic({name: "", date: "", remind_days: 30, legal_basis: ""})} data-testid="cmp-add-license">{tr("ops.cmp_add_license")}</button>}</h3>
    {lic && <section className="ui-panel tm-card cf-edit" data-testid="cmp-license-form">
      <div className="ui-form cf-form"><FormRow>
        <Field label={tr("ops.cmp_lic_name")}><input value={lic.name} onChange={e => setLic({...lic, name: e.target.value})} placeholder={tr("ops.cmp_lic_ph")}/></Field>
        <Field label={tr("ops.cmp_lic_date")}><input type="date" value={lic.date} onChange={e => setLic({...lic, date: e.target.value})}/></Field>
        <Field label={tr("ops.cmp_remind")}><input inputMode="numeric" value={lic.remind_days} onChange={e => setLic({...lic, remind_days: Number(e.target.value) || 0})}/></Field>
      </FormRow>
      <Field label={tr("ops.cmp_basis")} hint={tr("ops.cmp_basis_hint")}><input value={lic.legal_basis} onChange={e => setLic({...lic, legal_basis: e.target.value})}/></Field>
      <div className="tmRow"><button className="ui-btn is-primary" disabled={busy || !lic.name || !lic.date}
        onClick={async () => { const r = await run(() => apiOps.createComplianceRule({company_id: cid, name: lic.name, category: "license", frequency: "once",
          due_rule: {type: "fixed_date", date: lic.date}, remind_days: lic.remind_days, legal_basis: lic.legal_basis}), tr("ops.saved_short")); if (r) setLic(null); }}>{tr("ops.save")}</button>
        <button className="ui-btn is-ghost" onClick={() => setLic(null)}>{tr("ops.cancel")}</button></div></div>
    </section>}
    {!d.rules.length ? <EmptyState mood="chao" title={tr("ops.cmp_no_rules")} testId="cmp-no-rules">{tr("ops.cmp_no_rules_hint")}</EmptyState>
      : <div className="ui-panel"><table className="ui-table" data-testid="cmp-rules"><tbody>{d.rules.map((r: any) => <tr key={r.id} className={r.enabled ? "" : "is-off"}>
        <td><b>{r.name}</b> {r.needs_review && <span className="ui-pill is-wait">{tr("ops.cmp_review")}</span>}
          {!r.enabled && <span className="ui-pill">{tr("ops.cmp_off")}</span>}
          <div><small>{r.legal_basis || tr("ops.cmp_no_basis")}</small></div>{r.note && <div><small>⚠ {r.note}</small></div>}</td>
        <td><small>{freq(r)} · {tr("ops.cmp_remind_n", {p0: r.remind_days})}</small></td>
        <td><span className={"ui-pill " + (r.applies ? "is-ok" : "")}>{r.applies ? tr("ops.cmp_applies") : tr("ops.cmp_not_applies")}</span></td>
        <td style={{textAlign: "right", whiteSpace: "nowrap"}}>{isAdmin && <button className="ui-btn is-ghost is-sm" disabled={busy}
          onClick={() => run(() => apiOps.updateComplianceRule(r.id, {enabled: !r.enabled}), tr("ops.saved_short"))}>{r.enabled ? tr("ops.cmp_turn_off") : tr("ops.cmp_turn_on")}</button>}
          {isAdmin && r.source === "custom" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiOps.deleteComplianceRule(r.id), tr("ops.saved_short"))}>✕</button>}</td>
      </tr>)}</tbody></table></div>}
  </section>;
}

// ===================================================================== Chẩn đoán sẵn sàng agent (D8)

export function ReadinessTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiOps.readiness(companyId), [companyId]);
  const [ans, setAns] = useState<any>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  useEffect(() => { if (data) setAns({...((data as any).assessment?.answers || {})}); }, [data]);
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="rd-error"/>;
  if (!data || !ans) return <SkeletonRows n={5} h={44}/>;
  const d: any = data, a = d.assessment;
  async function assess() {
    setBusy(true); setError(null);
    try { const r = await apiOps.assessReadiness({company_id: companyId ?? d.company_id, answers: ans}); toast(tr("ops.rd_done", {p0: r.score})); await reload(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const lvlPill = (k: string) => k === "pilot_ready" ? "is-ok" : k === "building" ? "is-wait" : "is-risk";
  return <section className="ui-section" data-testid="readiness">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("ops.rd_explain")}</p>
    {!a ? <EmptyState mood="chao" title={tr("ops.rd_empty")} testId="rd-empty">{tr("ops.rd_empty_hint")}</EmptyState> : <>
      <div className="ui-grid is-2">
        <section className="ui-panel tm-card" data-testid="rd-score">
          <div className="tm-card-head"><div><b>{tr("ops.rd_score")}</b><span>{tr(`ops.rd_trigger_${a.trigger}` as Key)} · {new Date(a.created_at + "Z").toLocaleString(intlLocale())}</span></div>
            <span className={"ui-pill " + lvlPill(a.level)}>{tr(`ops.rd_lv_${a.level}` as Key)}</span></div>
          <div className="ops-big"><b>{a.score}</b><span>/100</span>{a.previous_score != null && <small> ({a.score >= a.previous_score ? "+" : ""}{a.score - a.previous_score} {tr("ops.rd_vs_prev")})</small>}</div>
          <table className="ui-table"><tbody>{a.layers.map((l: any) => <tr key={l.key}>
            <td>{tr(`ops.rd_l_${l.key}` as Key)}</td><td><Bar p={l.score}/> {l.score}</td>
            <td style={{textAlign: "right"}}>{l.todo ? <Link href={l.fix_href}>{tr("ops.rd_todo", {p0: l.todo})}</Link> : "✓"}</td></tr>)}</tbody></table>
        </section>
        <section className="ui-panel tm-card" data-testid="rd-lighthouse">
          <div className="tm-card-head"><div><b>{tr("ops.rd_lighthouse")}</b><span>{tr("ops.rd_lighthouse_desc")}</span></div>
            {a.lighthouse?.score ? <span className="ui-pill is-info">{a.lighthouse.score}/100</span> : null}</div>
          {a.lighthouse?.process_id ? <p className="ops-lh"><b>{a.lighthouse.name}</b></p> : <p>{tr("ops.rd_no_lighthouse")}</p>}
          <ul className="ops-issues ops-lh-list">{(a.lighthouse?.reasons || []).map((r: string, i: number) => <li key={i}>• {r}</li>)}</ul>
          {a.lighthouse?.process_id && <><b>{tr("ops.rd_next")}</b>
            <ol className="ops-steps">{[1, 2, 3].map(i => <li key={i}>{tr(`ops.rd_ns_${i}` as Key)}</li>)}</ol></>}
          <Link className="ui-btn is-ghost is-sm" href={a.lighthouse?.fix_href || "#"}>{tr("ops.rd_open_processes")}</Link>
        </section>
      </div>
      <h3 className="ops-cat">{tr("ops.rd_checklist")}</h3>
      <div className="ui-panel"><ul className="ops-check" data-testid="rd-checklist">{a.checks.map((c: any) => <li key={c.key} className={c.ok ? "is-ok" : ""}>
        <span className="ops-tick">{c.ok ? "✓" : c.score > 0 ? "◐" : "○"}</span>
        <span className="ui-grow"><b>{tr(`ops.rd_c_${c.key}` as Key)}</b> <small>— {c.detail}</small></span>
        {!c.ok && <Link className="ui-btn is-ghost is-sm" href={c.fix_href}>{tr("ops.rd_fix")}</Link>}</li>)}</ul></div>
    </>}
    <h3 className="ops-cat">{tr("ops.rd_questions")}</h3>
    <section className="ui-panel tm-card" data-testid="rd-questions">
      <fieldset disabled={!can || busy} className="ui-form cf-form">
        {d.questions.map((q: any) => <Field key={q.key} label={tr(`ops.rd_q_${q.key}` as Key)}>
          <select value={ans[q.key] || ""} onChange={e => setAns({...ans, [q.key]: e.target.value || undefined})} data-testid={`rd-q-${q.key}`}>
            <option value="">{tr("ops.choose")}</option>{q.options.map((o: string) => <option key={o} value={o}>{tr(`ops.rd_a_${q.key}_${o}` as Key)}</option>)}</select></Field>)}
        <Field label={tr("ops.rd_q_goal")}><input value={ans.goal || ""} onChange={e => setAns({...ans, goal: e.target.value})}/></Field>
      </fieldset>
      {can ? <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} onClick={assess} data-testid="rd-assess">{a ? tr("ops.rd_reassess") : tr("ops.rd_assess")}</button></div>
        : <small>{tr("ops.need_manager")}</small>}
    </section>
  </section>;
}
