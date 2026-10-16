"use client";
// M2e — công ty agent-native trong Đội ngũ: Luật cứng (M2e.2). Luật được cưỡng chế lúc chạy bởi guard plugin
// trên gateway (viết lại / che chữ / chặn gửi / chặn tool / chờ duyệt) và ở cổng MCP — không chỉ là chữ trong AGENTS.md.
import {useState} from "react";
import {apiNative, apiCompany} from "../lib/api";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {t as tr, type Key, intlLocale} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

const pct = (r: number | null | undefined) => r == null ? "—" : `${Math.round(r * 1000) / 10}%`;
const EMPTY_RULE = {name: "", kind: "phrase", pattern: "", action: "revise", message: "", external_only: false,
  position_id: null as number | null, source_ref: ""};

export function Stats({items}: {items: [string, any][]}) {
  return <div className="ui-grid is-3">{items.map(([label, v], i) => <section key={i} className="ui-panel tm-card">
    <small>{label}</small><div className="ops-big"><b className="ui-num">{v}</b></div></section>)}</div>;
}

export function RulesTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiNative.rules(companyId), [companyId]);
  const pos = useLoad(() => apiCompany.positions(companyId), [companyId]);
  const [form, setForm] = useState<any>(null), [busy, setBusy] = useState(false);
  const [probe, setProbe] = useState({text: "", tool: "", external: true}), [probeOut, setProbeOut] = useState<any>(null);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="rules-error"/>;
  if (!data) return <SkeletonRows n={4} h={44}/>;
  const d: any = data;
  const kinds: any[] = d.kinds || [];
  const actionsOf = (k: string) => kinds.find(x => x.key === k)?.actions || [];
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); setForm(null); await reload(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const save = () => run(() => form.id ? apiNative.updateRule(form.id, form)
    : apiNative.createRule({...form, company_id: companyId ?? d.company_id}), tr("native.rule_saved"));
  const fromTemplate = (key: string) => run(() => apiNative.createRule({company_id: companyId ?? d.company_id, template: key}), tr("native.rule_saved"));
  async function test() {
    setBusy(true);
    try { setProbeOut(await apiNative.testRules({company_id: companyId ?? d.company_id, ...probe})); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const positions: any[] = (pos.data as any)?.items || [];
  return <section className="ui-section" data-testid="rules">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("native.rules_explain")}</p>
    <Stats items={[[tr("native.rules_active"), d.rules.filter((r: any) => r.enabled).length],
      [tr("native.violations_30d"), d.violations_30d],
      [tr("native.charter_enforced"), `${d.prohibitions.filter((p: any) => p.enforced).length}/${d.prohibitions.length}`]]}/>

    {d.prohibitions.length > 0 && <section className="ui-panel tm-card" data-testid="rules-charter">
      <div className="tm-card-head"><div><b>{tr("native.charter_title")}</b><span>{tr("native.charter_desc")}</span></div></div>
      <ul className="ops-check">{d.prohibitions.map((p: any) => <li key={p.index} className={p.enforced ? "is-ok" : ""}>
        <span className="ops-tick">{p.enforced ? "✓" : "○"}</span>
        <span className="ui-grow">{p.text} <small>— {p.enforced ? tr("native.enforced") : tr("native.text_only")}</small></span>
        {!p.enforced && can && <button className="ui-btn is-ghost is-sm" onClick={() => setForm({...EMPTY_RULE, name: p.text, source_ref: p.index})}>{tr("native.make_rule")}</button>}
      </li>)}</ul>
    </section>}

    <div className="tmRow">
      {can && <button className="ui-btn is-primary" disabled={busy} onClick={() => setForm({...EMPTY_RULE})} data-testid="rule-new">{tr("native.rule_new")}</button>}
      {can && d.templates.map((t: any) => <button key={t.key} className="ui-btn is-ghost is-sm" disabled={busy}
        onClick={() => fromTemplate(t.key)} data-testid={`rule-tpl-${t.key}`}>+ {tr(`native.tpl_${t.key}` as Key)}</button>)}
    </div>

    {form && <section className="ui-panel tm-card" data-testid="rule-form">
      <fieldset className="ui-form cf-form" disabled={busy}>
        <FormRow>
          <Field label={tr("native.f_name")}><input value={form.name} onChange={e => setForm({...form, name: e.target.value})} data-testid="rf-name"/></Field>
          <Field label={tr("native.f_kind")}><select value={form.kind} data-testid="rf-kind"
            onChange={e => setForm({...form, kind: e.target.value, action: actionsOf(e.target.value)[0]})}>
            {kinds.map(k => <option key={k.key} value={k.key}>{tr(`native.kind_${k.key}` as Key)}</option>)}</select></Field>
          <Field label={tr("native.f_action")}><select value={form.action} onChange={e => setForm({...form, action: e.target.value})} data-testid="rf-action">
            {actionsOf(form.kind).map((a: string) => <option key={a} value={a}>{tr(`native.act_${a}` as Key)}</option>)}</select></Field>
        </FormRow>
        <Field label={tr(`native.pat_${form.kind}` as Key)} hint={tr(`native.pat_hint_${form.kind}` as Key)}>
          {form.kind === "phrase" ? <textarea rows={3} value={form.pattern} onChange={e => setForm({...form, pattern: e.target.value})} data-testid="rf-pattern"/>
            : <input value={form.pattern} onChange={e => setForm({...form, pattern: e.target.value})} data-testid="rf-pattern"/>}</Field>
        <FormRow>
          <Field label={tr("native.f_scope")}><select value={form.position_id ?? ""} data-testid="rf-scope"
            onChange={e => setForm({...form, position_id: e.target.value ? Number(e.target.value) : null})}>
            <option value="">{tr("native.scope_company")}</option>
            {positions.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
          <Field label={tr("native.f_charter")}><select value={form.source_ref || ""} onChange={e => setForm({...form, source_ref: e.target.value})}>
            <option value="">—</option>{d.prohibitions.map((p: any) => <option key={p.index} value={p.index}>{p.text}</option>)}</select></Field>
        </FormRow>
        <Field label={tr("native.f_message")}><input value={form.message} onChange={e => setForm({...form, message: e.target.value})}/></Field>
        <label className="tmInline"><input type="checkbox" checked={!!form.external_only}
          onChange={e => setForm({...form, external_only: e.target.checked})}/> {tr("native.f_external_only")}</label>
      </fieldset>
      <div className="tmRow">
        <button className="ui-btn is-primary" disabled={busy || !form.name || !form.pattern} onClick={save} data-testid="rf-save">{tr("native.save")}</button>
        <button className="ui-btn is-ghost" onClick={() => setForm(null)}>{tr("native.cancel")}</button>
      </div>
    </section>}

    {d.rules.length === 0 ? <EmptyState mood="chao" title={tr("native.rules_empty")} testId="rules-empty">{tr("native.rules_empty_hint")}</EmptyState>
      : <div className="ui-panel"><table className="ui-table" data-testid="rules-table"><thead><tr>
        <th>{tr("native.f_name")}</th><th>{tr("native.f_kind")}</th><th>{tr("native.f_scope")}</th><th>{tr("native.f_action")}</th><th></th></tr></thead>
        <tbody>{d.rules.map((r: any) => <tr key={r.id} className={r.enabled ? "" : "is-muted"}>
          <td><b>{r.name}</b><br/><small><code>{r.pattern}</code>{r.external_only ? ` · ${tr("native.external_only")}` : ""}</small></td>
          <td>{tr(`native.kind_${r.kind}` as Key)}</td>
          <td>{r.position || tr("native.scope_company")}</td>
          <td><span className="ui-pill is-info">{tr(`native.act_${r.action}` as Key)}</span></td>
          <td style={{textAlign: "right"}}>{can && <>
            <button className="ui-btn is-ghost is-sm" onClick={() => setForm({...r})}>{tr("native.edit")}</button>
            <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiNative.updateRule(r.id, {enabled: !r.enabled}), tr("native.rule_saved"))}>
              {r.enabled ? tr("native.disable") : tr("native.enable")}</button>
            <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiNative.deleteRule(r.id), tr("native.rule_deleted"))}>{tr("native.delete")}</button></>}</td>
        </tr>)}</tbody></table></div>}

    <section className="ui-panel tm-card" data-testid="rules-probe">
      <div className="tm-card-head"><div><b>{tr("native.probe_title")}</b><span>{tr("native.probe_desc")}</span></div></div>
      <FormRow>
        <Field label={tr("native.probe_text")}><input value={probe.text} onChange={e => setProbe({...probe, text: e.target.value})} data-testid="probe-text"/></Field>
        <Field label={tr("native.probe_tool")}><input value={probe.tool} onChange={e => setProbe({...probe, tool: e.target.value})} placeholder="company_delegate_external"/></Field>
      </FormRow>
      <div className="tmRow"><label className="tmInline"><input type="checkbox" checked={probe.external} onChange={e => setProbe({...probe, external: e.target.checked})}/> {tr("native.probe_external")}</label>
        <button className="ui-btn" disabled={busy || (!probe.text && !probe.tool)} onClick={test} data-testid="probe-run">{tr("native.probe_run")}</button></div>
      {probeOut && <div data-testid="probe-out">
        {probeOut.hits.length === 0 && !probeOut.tool ? <p>✓ {tr("native.probe_clean")}</p> : <ul className="ops-issues">
          {probeOut.hits.map((h: any, i: number) => <li key={i}>• {tr(`native.act_${h.action}` as Key)}: <b>{h.match}</b> — {h.message}</li>)}
          {probeOut.tool && <li>• {tr(`native.act_${probeOut.tool.action}` as Key)}: {probe.tool} — {probeOut.tool.message}</li>}</ul>}
        {probeOut.scrubbed && probeOut.scrubbed !== probe.text && <p><small>{tr("native.probe_scrubbed")}</small> {probeOut.scrubbed}</p>}
      </div>}
    </section>

    <h3 className="ops-cat">{tr("native.seat_compliance")}</h3>
    <div className="ui-panel"><table className="ui-table" data-testid="rules-seats"><thead><tr>
      <th>{tr("native.seat")}</th><th>{tr("native.rules_n")}</th><th>{tr("native.runs_30d")}</th><th>{tr("native.violations")}</th><th>{tr("native.compliance_rate")}</th></tr></thead>
      <tbody>{d.seats.map((s: any) => <tr key={s.member_id}><td>{s.name}</td><td className="ui-num">{s.rules}</td>
        <td className="ui-num">{s.runs}</td><td className="ui-num">{s.violations}</td><td className="ui-num">{pct(s.rate)}</td></tr>)}</tbody></table>
      <small>{tr("native.compliance_note")}</small></div>

    <h3 className="ops-cat">{tr("native.violation_log")}</h3>
    {d.violations.length === 0 ? <p><small>{tr("native.no_violations")}</small></p>
      : <div className="ui-panel"><table className="ui-table" data-testid="rules-violations"><tbody>{d.violations.map((v: any) => <tr key={v.id}>
        <td>{new Date(v.created_at + "Z").toLocaleString(intlLocale())}</td><td>{v.seat || "—"}</td>
        <td><span className="ui-pill is-risk">{tr(`native.act_${v.action}` as Key)}</span> <small>{tr(`native.hook_${v.hook}` as Key)}</small></td>
        <td><small>{v.excerpt}</small></td></tr>)}</tbody></table></div>}
  </section>;
}

// ===================================================================== M2e.3 hợp đồng dữ liệu vào/ra
// Schema kết quả soạn bằng bảng trường (sinh tập con JSON Schema) hoặc sửa JSON trực tiếp; mẫu có sẵn.
type FieldRow = {name: string; type: string; required: boolean; enum: string; min: string; max: string; description: string; extra: any};
const FIELD_TYPES = ["string", "number", "integer", "boolean", "array", "object"];
const COND = ["==", "!=", ">", ">=", "<", "<=", "empty", "not_empty"];
function rowsOf(schema: any): FieldRow[] {
  const props = schema?.properties || {}, req: string[] = schema?.required || [];
  return Object.entries(props).map(([name, v]: [string, any]) => {
    const {type, enum: en, minimum, maximum, minLength, maxLength, description, ...extra} = v || {};
    const isStr = type === "string";
    return {name, type: type || "string", required: req.includes(name), enum: (en || []).join(", "),
      min: String((isStr ? minLength : minimum) ?? ""), max: String((isStr ? maxLength : maximum) ?? ""), description: description || "", extra};
  });
}
function schemaOf(rows: FieldRow[]): any {
  const properties: any = {};
  for (const r of rows) {
    if (!r.name.trim()) continue;
    const p: any = {...r.extra, type: r.type};
    const conv = (x: string) => r.type === "string" ? x.trim() : x.trim();
    if (r.enum.trim()) p.enum = r.enum.split(",").map(x => conv(x)).filter(Boolean).map(x => r.type === "number" || r.type === "integer" ? Number(x) : x);
    if (r.min !== "") p[r.type === "string" ? "minLength" : r.type === "array" ? "minItems" : "minimum"] = Number(r.min);
    if (r.max !== "") p[r.type === "string" ? "maxLength" : r.type === "array" ? "maxItems" : "maximum"] = Number(r.max);
    if (r.description.trim()) p.description = r.description.trim();
    properties[r.name.trim()] = p;
  }
  return {type: "object", properties, required: rows.filter(r => r.required && r.name.trim()).map(r => r.name.trim()), additionalProperties: false};
}
const EMPTY_CONTRACT = {name: "", description: "", position_id: null as number | null, max_attempts: 3, outcome_field: "",
  output_schema: {type: "object", properties: {}, required: []}, input_schema: null as any, acceptance: [] as any[]};

export function ContractsTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiNative.contracts(companyId), [companyId]);
  const pos = useLoad(() => apiCompany.positions(companyId), [companyId]);
  const [form, setForm] = useState<any>(null), [rows, setRows] = useState<FieldRow[]>([]), [raw, setRaw] = useState<string | null>(null);
  const [inputRaw, setInputRaw] = useState(""), [busy, setBusy] = useState(false);
  const [probe, setProbe] = useState<{id: number | null; text: string}>({id: null, text: ""}), [probeOut, setProbeOut] = useState<any>(null);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="contracts-error"/>;
  if (!data) return <SkeletonRows n={4} h={44}/>;
  const d: any = data;
  const positions: any[] = (pos.data as any)?.items || [];
  const open = (c: any) => {
    setForm({...EMPTY_CONTRACT, ...c}); setRows(rowsOf(c.output_schema)); setRaw(null);
    setInputRaw(c.input_schema ? JSON.stringify(c.input_schema, null, 1) : "");
  };
  async function run(fn: () => Promise<any>, ok: string, close = true) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); if (close) setForm(null); await reload(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  function body() {
    let output_schema: any = schemaOf(rows), input_schema: any = null;
    if (raw != null) output_schema = JSON.parse(raw);
    if (inputRaw.trim()) input_schema = JSON.parse(inputRaw);
    return {name: form.name, description: form.description || "", position_id: form.position_id ?? null,
      max_attempts: Number(form.max_attempts) || 3, outcome_field: form.outcome_field || "", output_schema, input_schema,
      acceptance: (form.acceptance || []).filter((a: any) => (a.text || "").trim() || a.field).map((a: any) => a.field
        ? {...a, value: [">", ">=", "<", "<="].includes(a.op) ? Number(a.value) : a.value === "true" ? true : a.value === "false" ? false : a.value}
        : {text: a.text})};
  }
  const save = () => { let b: any; try { b = body(); } catch (e) { setError(new Error(tr("native.c_bad_json"))); return; }
    run(() => form.id ? apiNative.updateContract(form.id, b) : apiNative.createContract({...b, company_id: companyId ?? d.company_id}), tr("native.c_saved")); };
  const fromTemplate = (key: string) => run(() => apiNative.createContract({company_id: companyId ?? d.company_id, template: key}), tr("native.c_saved"));
  async function test() {
    if (!probe.id) return;
    setBusy(true);
    try { setProbeOut(await apiNative.validateOutput(probe.id, probe.text)); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const setRow = (i: number, k: keyof FieldRow, v: any) => setRows(rows.map((r, j) => j === i ? {...r, [k]: v} : r));
  const setAcc = (i: number, k: string, v: any) => setForm({...form, acceptance: form.acceptance.map((a: any, j: number) => j === i ? {...a, [k]: v} : a)});
  const fieldNames = (raw != null ? (() => { try { return Object.keys(JSON.parse(raw).properties || {}); } catch { return []; } })() : rows.map(r => r.name)).filter(Boolean);
  const cr = d.company_rate || {};
  return <section className="ui-section" data-testid="contracts">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("native.contracts_explain")}</p>
    <Stats items={[[tr("native.c_active"), d.items.length], [tr("native.c_rate_30d"), pct(cr.rate)],
      [tr("native.c_first_try"), pct(cr.first_try_rate)]]}/>
    <div className="tmRow">
      {can && <button className="ui-btn is-primary" disabled={busy} onClick={() => open({...EMPTY_CONTRACT})} data-testid="contract-new">{tr("native.c_new")}</button>}
      {can && d.templates.map((t: any) => <button key={t.key} className="ui-btn is-ghost is-sm" disabled={busy} title={t.fields}
        onClick={() => fromTemplate(t.key)} data-testid={`contract-tpl-${t.key}`}>+ {tr(`native.ctpl_${t.key}` as Key)}</button>)}
    </div>

    {form && <section className="ui-panel tm-card" data-testid="contract-form">
      <fieldset className="ui-form cf-form" disabled={busy}>
        <FormRow>
          <Field label={tr("native.f_name")}><input value={form.name} onChange={e => setForm({...form, name: e.target.value})} data-testid="cf-name"/></Field>
          <Field label={tr("native.c_position")} hint={tr("native.c_position_hint")}><select value={form.position_id ?? ""}
            onChange={e => setForm({...form, position_id: e.target.value ? Number(e.target.value) : null})}>
            <option value="">—</option>{positions.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
          <Field label={tr("native.c_max_attempts")}><input inputMode="numeric" value={form.max_attempts}
            onChange={e => setForm({...form, max_attempts: e.target.value})}/></Field>
          <Field label={tr("native.c_outcome_field")} hint={tr("native.c_outcome_hint")}><select value={form.outcome_field || ""}
            onChange={e => setForm({...form, outcome_field: e.target.value})}>
            <option value="">—</option>{fieldNames.map(n => <option key={n} value={n}>{n}</option>)}</select></Field>
        </FormRow>
        <Field label={tr("native.c_description")}><input value={form.description || ""} onChange={e => setForm({...form, description: e.target.value})}/></Field>
        <div className="ui-field"><span className="ui-field-label">{tr("native.c_output_schema")}
          <button type="button" className="ui-btn is-ghost is-sm" onClick={() => setRaw(raw == null ? JSON.stringify(schemaOf(rows), null, 1) : null)}
            data-testid="cf-raw">{raw == null ? tr("native.c_edit_json") : tr("native.c_edit_table")}</button></span>
          {raw != null ? <textarea rows={10} className="ops-json" value={raw} onChange={e => setRaw(e.target.value)} data-testid="cf-raw-text"/>
            : <><table className="ui-table cf-fields" data-testid="cf-fields"><thead><tr><th>{tr("native.c_field")}</th><th>{tr("native.c_type")}</th>
              <th>{tr("native.c_required")}</th><th>{tr("native.c_enum")}</th><th>{tr("native.c_min")}</th><th>{tr("native.c_max")}</th><th>{tr("native.c_desc")}</th><th></th></tr></thead>
              <tbody>{rows.map((r, i) => <tr key={i}>
                <td><input value={r.name} onChange={e => setRow(i, "name", e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))} aria-label={tr("native.c_field")}/></td>
                <td><select value={r.type} onChange={e => setRow(i, "type", e.target.value)} aria-label={tr("native.c_type")}>
                  {FIELD_TYPES.map(t => <option key={t} value={t}>{tr(`native.ct_${t}` as Key)}</option>)}</select></td>
                <td><input type="checkbox" checked={r.required} onChange={e => setRow(i, "required", e.target.checked)} aria-label={tr("native.c_required")}/></td>
                <td><input value={r.enum} onChange={e => setRow(i, "enum", e.target.value)} placeholder="a, b" aria-label={tr("native.c_enum")}/></td>
                <td><input className="ops-min" value={r.min} onChange={e => setRow(i, "min", e.target.value)} aria-label={tr("native.c_min")}/></td>
                <td><input className="ops-min" value={r.max} onChange={e => setRow(i, "max", e.target.value)} aria-label={tr("native.c_max")}/></td>
                <td><input value={r.description} onChange={e => setRow(i, "description", e.target.value)} aria-label={tr("native.c_desc")}/></td>
                <td><button type="button" className="ui-btn is-ghost is-sm" onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label={tr("native.delete")}>✕</button></td>
              </tr>)}</tbody></table>
              <button type="button" className="ui-btn is-ghost is-sm" data-testid="cf-add-field"
                onClick={() => setRows([...rows, {name: "", type: "string", required: true, enum: "", min: "", max: "", description: "", extra: {}}])}>{tr("native.c_add_field")}</button></>}
          <small className="tmGuide">{tr("native.c_schema_hint", {p0: (d.keywords || []).join(", ")})}</small>
        </div>
        <div className="ui-field"><span className="ui-field-label">{tr("native.c_acceptance")}</span>
          {(form.acceptance || []).map((a: any, i: number) => <div key={i} className="tmRow cf-acc">
            <input className="ui-grow" value={a.text || ""} placeholder={tr("native.c_acc_text")} onChange={e => setAcc(i, "text", e.target.value)}/>
            <select value={a.field || ""} onChange={e => setAcc(i, "field", e.target.value)} aria-label={tr("native.c_field")}>
              <option value="">{tr("native.c_acc_text_only")}</option>{fieldNames.map(n => <option key={n} value={n}>{n}</option>)}</select>
            {a.field && <><select value={a.op || "=="} onChange={e => setAcc(i, "op", e.target.value)} aria-label="op">
              {COND.map(o => <option key={o} value={o}>{o}</option>)}</select>
              {!["empty", "not_empty"].includes(a.op) && <input className="ops-min" value={a.value ?? ""} onChange={e => setAcc(i, "value", e.target.value)} aria-label="value"/>}</>}
            <button type="button" className="ui-btn is-ghost is-sm" onClick={() => setForm({...form, acceptance: form.acceptance.filter((_: any, j: number) => j !== i)})}>✕</button>
          </div>)}
          <button type="button" className="ui-btn is-ghost is-sm" onClick={() => setForm({...form, acceptance: [...(form.acceptance || []), {text: "", field: "", op: "==", value: ""}]})}>{tr("native.c_add_acc")}</button>
        </div>
        <Field label={tr("native.c_input_schema")} hint={tr("native.c_input_hint")}>
          <textarea rows={3} className="ops-json" value={inputRaw} onChange={e => setInputRaw(e.target.value)} placeholder='{"type": "object", "properties": {"order_id": {"type": "string"}}}'/></Field>
      </fieldset>
      <div className="tmRow">
        <button className="ui-btn is-primary" disabled={busy || !form.name} onClick={save} data-testid="cf-save">{tr("native.save")}</button>
        <button className="ui-btn is-ghost" onClick={() => setForm(null)}>{tr("native.cancel")}</button>
      </div>
    </section>}

    {d.items.length === 0 ? <EmptyState mood="chao" title={tr("native.c_empty")} testId="contracts-empty">{tr("native.c_empty_hint")}</EmptyState>
      : <div className="ui-panel"><table className="ui-table" data-testid="contracts-table"><thead><tr>
        <th>{tr("native.f_name")}</th><th>{tr("native.c_position")}</th><th>{tr("native.c_used_in")}</th><th>{tr("native.c_rate")}</th><th></th></tr></thead>
        <tbody>{d.items.map((c: any) => <tr key={c.id}>
          <td><b>{c.name}</b> <small>v{c.version}</small><br/><small><code>{c.fields}</code></small>
            {(c.acceptance || []).length > 0 && <div><small>{tr("native.c_acceptance")}: {c.acceptance.map((a: any) => a.text || a.field).join("; ")}</small></div>}</td>
          <td>{c.position || "—"}</td>
          <td>{c.steps.length ? c.steps.map((s: any) => `#${s.process_id} B${s.seq} ${s.name}`).join(", ") : "—"}</td>
          <td className="ui-num">{pct(c.stats?.rate)}<br/><small>{c.stats?.valid ?? 0}/{c.stats?.submissions ?? 0}</small></td>
          <td style={{textAlign: "right"}}>
            <button className="ui-btn is-ghost is-sm" onClick={() => { setProbe({id: c.id, text: probe.text}); setProbeOut(null); }} data-testid={`contract-try-${c.id}`}>{tr("native.c_try")}</button>
            {can && <><button className="ui-btn is-ghost is-sm" onClick={() => open(c)}>{tr("native.edit")}</button>
              <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiNative.archiveContract(c.id), tr("native.c_archived"))}>{tr("native.c_archive")}</button></>}</td>
        </tr>)}</tbody></table></div>}

    {probe.id && <section className="ui-panel tm-card" data-testid="contract-probe">
      <div className="tm-card-head"><div><b>{tr("native.c_try_title", {p0: d.items.find((c: any) => c.id === probe.id)?.name || ""})}</b><span>{tr("native.c_try_desc")}</span></div></div>
      <textarea rows={6} className="ops-json" value={probe.text} onChange={e => setProbe({...probe, text: e.target.value})} placeholder='{"order_id": "DH-1024", ...}' data-testid="contract-probe-text"/>
      <div className="tmRow"><button className="ui-btn" disabled={busy || !probe.text.trim()} onClick={test} data-testid="contract-probe-run">{tr("native.probe_run")}</button></div>
      {probeOut && <div data-testid="contract-probe-out">{probeOut.valid ? <p>✓ {tr("native.c_valid")}</p>
        : <ul className="ops-issues">{probeOut.errors.map((e: any, i: number) => <li key={i}>• <code>{e.path}</code>: {e.message}</li>)}</ul>}</div>}
    </section>}

    <h3 className="ops-cat">{tr("native.c_seat_rate")}</h3>
    <div className="ui-panel"><table className="ui-table" data-testid="contracts-seats"><thead><tr>
      <th>{tr("native.seat")}</th><th>{tr("native.c_submissions")}</th><th>{tr("native.c_valid_n")}</th><th>{tr("native.c_rate")}</th><th>{tr("native.c_first_try")}</th></tr></thead>
      <tbody>{d.seats.map((s: any) => <tr key={s.member_id}><td>{s.name}{s.member_type === "agent" ? " · AI" : ""}</td><td className="ui-num">{s.submissions}</td>
        <td className="ui-num">{s.valid}</td><td className="ui-num">{pct(s.rate)}</td><td className="ui-num">{pct(s.first_try_rate)}</td></tr>)}</tbody></table>
      <small>{tr("native.c_rate_note")}</small></div>
    {d.positions.length > 0 && <div className="ui-panel"><table className="ui-table" data-testid="contracts-positions"><thead><tr>
      <th>{tr("native.c_position")}</th><th>{tr("native.c_count")}</th><th>{tr("native.c_submissions")}</th><th>{tr("native.c_rate")}</th></tr></thead>
      <tbody>{d.positions.map((p: any) => <tr key={p.position_id}><td>{p.title}</td><td className="ui-num">{p.contracts}</td>
        <td className="ui-num">{p.submissions}</td><td className="ui-num">{pct(p.rate)}</td></tr>)}</tbody></table></div>}

    <h3 className="ops-cat">{tr("native.c_recent")}</h3>
    {d.recent.length === 0 ? <p><small>{tr("native.c_no_recent")}</small></p>
      : <div className="ui-panel"><table className="ui-table" data-testid="contracts-recent"><tbody>{d.recent.map((o: any) => <tr key={o.id}>
        <td>{new Date(o.created_at + "Z").toLocaleString(intlLocale())}</td><td>{o.seat || "—"}</td>
        <td><a href={`/app/tasks/${o.task_id}`}>#{o.task_id}</a> · {tr("native.c_attempt", {p0: o.attempt})}</td>
        <td>{o.valid ? <span className="ui-pill is-ok">{tr("native.c_ok")}</span> : <span className="ui-pill is-risk">{tr("native.c_bad")}</span>}
          {!o.valid && <div><small>{o.errors.slice(0, 3).map((e: any) => `${e.path}: ${e.message}`).join("; ")}</small></div>}</td></tr>)}</tbody></table></div>}
  </section>;
}
