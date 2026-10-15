"use client";
// M2b — nền công ty trong Đội ngũ: Hồ sơ công ty (pháp nhân + hiến chương), Chức danh
// (JD, KPI, định biên, chỗ trống), Phân quyền (ma trận ai duyệt gì theo tiền USD / loại việc / rủi ro).
// Hiến chương và JD/KPI được biên dịch vào AGENTS.md của agent — giao diện nói rõ điều đó.
import {useEffect, useState} from "react";
import {apiCompany, errorText} from "../lib/api";
import {EmptyState, ErrorBanner, Notice} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {t as tr, type Key} from "../lib/i18n";

const lines = (s: string) => s.split("\n").map(x => x.trim()).filter(Boolean);
const usd = (v: number | null | undefined) => v == null ? "" : "$" + (Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(2));
export const actLabel = (k: string) => tr(`company.act_${k}` as Key);
export const whoLabel = (k: string) => tr(`company.who_${k}` as Key);
export function bandText(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo == null && hi == null) return tr("company.band_any");
  if (!lo && hi != null) return tr("company.band_under", {p0: usd(hi)});
  if (hi == null) return tr("company.band_from", {p0: usd(lo)});
  return `${usd(lo)}–${usd(hi)}`;
}

function useLoad<T>(fn: () => Promise<T>, deps: any[]) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState<unknown>(null);
  const reload = () => fn().then(d => { setData(d); setError(null); }).catch(setError);
  useEffect(() => { setData(null); reload(); /* eslint-disable-next-line */ }, deps);
  return {data, error, reload, setError};
}

// ===================================================================== Hồ sơ công ty

export function CompanyProfileTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiCompany.profile(companyId), [companyId]);
  const [f, setF] = useState<any>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.manage_roles || !!caps?.create_company;
  useEffect(() => {
    if (!data) return;
    const d: any = data;
    setF({...d, values: (d.values || []).join("\n"), prohibitions: (d.prohibitions || []).join("\n"),
          customer_promises: (d.customer_promises || []).join("\n"), business_lines: (d.business_lines || []).join("\n"),
          charter_capital_usd: d.charter_capital_usd ?? "", founded_on: d.founded_on || ""});
  }, [data]);
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="cp-error"/>;
  if (!f) return <SkeletonRows n={5} h={44}/>;
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  async function save() {
    setBusy(true); setError(null);
    try {
      const body = {company_id: companyId ?? f.company_id, legal_name: f.legal_name, entity_type: f.entity_type, tax_code: f.tax_code,
        legal_representative: f.legal_representative, representative_title: f.representative_title,
        registered_address: f.registered_address, charter_capital_note: f.charter_capital_note,
        charter_capital_usd: f.charter_capital_usd === "" ? null : Number(f.charter_capital_usd),
        founded_on: f.founded_on || null, business_lines: lines(f.business_lines), mission: f.mission,
        values: lines(f.values), brand_voice: f.brand_voice, prohibitions: lines(f.prohibitions),
        customer_promises: lines(f.customer_promises)};
      const r = await apiCompany.saveProfile(body);
      toast(r.core_sync ? tr("company.saved_resync", {p0: r.charter_version}) : tr("company.saved"));
      await reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const d: any = data;
  return <div className="ui-grid is-2" data-testid="company-profile">
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>{tr("company.legal_title")}</b><span>{tr("company.legal_desc")}</span></div></div>
      {!can && <div className="ui-banner">{tr("company.need_admin")}</div>}
      <fieldset disabled={!can || busy} className="ui-form cf-form">
        <Field label={tr("company.legal_name")} hint={tr("company.legal_name_hint")}><input value={f.legal_name} onChange={set("legal_name")} data-testid="cp-legal-name"/></Field>
        <FormRow>
          <Field label={tr("company.entity_type")}><select value={f.entity_type} onChange={set("entity_type")} data-testid="cp-entity">
            <option value="">{tr("company.choose")}</option>
            {d.entity_types.map((e: any) => <option key={e.key} value={e.key} title={e.basis}>{tr(`company.et_${e.key}` as Key)}</option>)}
          </select></Field>
          <Field label={tr("company.tax_code")} hint={tr("company.tax_code_hint")}><input value={f.tax_code} onChange={set("tax_code")} inputMode="numeric" data-testid="cp-tax"/></Field>
        </FormRow>
        <FormRow>
          <Field label={tr("company.rep")}><input value={f.legal_representative} onChange={set("legal_representative")}/></Field>
          <Field label={tr("company.rep_title")}><input value={f.representative_title} onChange={set("representative_title")}/></Field>
        </FormRow>
        <Field label={tr("company.address")}><input value={f.registered_address} onChange={set("registered_address")}/></Field>
        <FormRow>
          <Field label={tr("company.capital")} hint={tr("company.capital_hint")}><input type="number" min={0} value={f.charter_capital_usd} onChange={set("charter_capital_usd")}/></Field>
          <Field label={tr("company.capital_note")}><input value={f.charter_capital_note} onChange={set("charter_capital_note")}/></Field>
        </FormRow>
        <FormRow>
          <Field label={tr("company.founded")}><input type="date" value={f.founded_on} onChange={set("founded_on")}/></Field>
        </FormRow>
        <Field label={tr("company.lines")} hint={tr("company.one_per_line")}><textarea rows={3} value={f.business_lines} onChange={set("business_lines")}/></Field>
      </fieldset>
      {d.warnings?.length > 0 && <Notice tone="wait" testId="cp-warnings">{d.warnings.map((w: string, i: number) => <div key={i}>⚠ {w}</div>)}</Notice>}
    </section>
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>{tr("company.charter_title")}</b><span>{tr("company.charter_desc")}</span></div>
        {d.charter_version ? <span className="ui-pill is-ok">v{d.charter_version}</span> : null}</div>
      <fieldset disabled={!can || busy} className="ui-form cf-form">
        <Field label={tr("company.mission")}><textarea rows={2} value={f.mission} onChange={set("mission")} data-testid="cp-mission"/></Field>
        <Field label={tr("company.values")} hint={tr("company.one_per_line")}><textarea rows={3} value={f.values} onChange={set("values")}/></Field>
        <Field label={tr("company.voice")} hint={tr("company.voice_hint")}><textarea rows={2} value={f.brand_voice} onChange={set("brand_voice")}/></Field>
        <Field label={tr("company.prohibitions")} hint={tr("company.prohibitions_hint")}><textarea rows={3} value={f.prohibitions} onChange={set("prohibitions")} data-testid="cp-prohibitions"/></Field>
        <Field label={tr("company.promises")} hint={tr("company.one_per_line")}><textarea rows={3} value={f.customer_promises} onChange={set("customer_promises")}/></Field>
      </fieldset>
      {can && <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} onClick={save} data-testid="cp-save">{busy ? tr("company.saving") : tr("company.save")}</button>
        <small>{tr("company.save_note")}</small></div>}
      {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
      {d.charter_text ? <details className="cf-preview" data-testid="cp-preview"><summary>{tr("company.preview", {p0: d.charter_chars, p1: d.charter_budget})}</summary>
        <pre>{d.charter_text}</pre></details>
        : <EmptyState compact mood="chao" title={tr("company.charter_empty")}>{tr("company.charter_empty_hint")}</EmptyState>}
    </section>
  </div>;
}

// ===================================================================== Chức danh

const EMPTY_POS = {title: "", department_id: "", job_description: "", responsibilities: "", headcount: 1, reports_to_position_id: "",
  allowed_tools: [] as string[], allowed_skills: "", kpis: [] as any[]};

export function PositionsTab({companyId, chart, caps}: {companyId: number | null; chart: any; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiCompany.positions(companyId), [companyId]);
  const [edit, setEdit] = useState<any>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.edit_org_chart || !!caps?.invite;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="pos-error"/>;
  if (!data) return <SkeletonRows n={4} h={56}/>;
  const d: any = data;
  const depts = chart?.departments || [];
  async function run(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await reload(); return r; }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  function open(p?: any) {
    setEdit(p ? {...p, department_id: p.department_id ?? "", reports_to_position_id: p.reports_to_position_id ?? "",
      responsibilities: (p.responsibilities || []).join("\n"), allowed_skills: (p.allowed_skills || []).join("\n"),
      kpis: (p.kpis || []).map((k: any) => ({...k, target: k.target ?? ""}))} : {...EMPTY_POS, kpis: []});
  }
  async function save() {
    const e = edit;
    const body: any = {title: e.title, department_id: e.department_id ? Number(e.department_id) : null,
      job_description: e.job_description, responsibilities: lines(e.responsibilities), headcount: Number(e.headcount),
      reports_to_position_id: e.reports_to_position_id ? Number(e.reports_to_position_id) : null,
      allowed_tools: e.allowed_tools, allowed_skills: lines(e.allowed_skills),
      kpis: e.kpis.filter((k: any) => k.name.trim()).map((k: any) => ({name: k.name, target: k.target === "" ? null : Number(k.target), unit: k.unit || "", period: k.period || "month"}))};
    const r = await run(() => e.id ? apiCompany.updatePosition(e.id, body) : apiCompany.createPosition({...body, company_id: companyId ?? d.company_id}),
      (x: any) => x.resync_agents?.length ? tr("company.pos_saved_resync", {p0: x.resync_agents.length}) : tr("company.pos_saved"));
    if (r) setEdit(null);
  }
  const t = d.totals;
  return <section className="ui-section" data-testid="positions">
    <div className="ui-toolbar">
      <div className="org-stats"><span><b>{t.positions}</b> {tr("company.positions")}</span><span><b>{t.filled}/{t.headcount}</b> {tr("company.filled")}</span>
        {t.vacancies ? <span className="is-warn" data-testid="pos-vacancies"><b>{t.vacancies}</b> {tr("company.vacancies")}</span> : null}</div>
      <span className="ui-grow"/>
      {can && d.unplaced.length > 0 && <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="pos-from-members"
        onClick={() => run(() => apiCompany.positionsFromMembers(companyId ?? d.company_id), (r: any) => tr("company.from_members_done", {p0: r.created, p1: r.placed}))}>{tr("company.from_members", {p0: d.unplaced.length})}</button>}
      {can && <button className="ui-btn is-primary is-sm" onClick={() => open()} data-testid="pos-new">{tr("company.new_position")}</button>}
    </div>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    {edit && <PositionForm edit={edit} setEdit={setEdit} depts={depts} positions={d.items} tools={d.tool_names} busy={busy} onSave={save}/>}
    {!d.items.length ? <EmptyState mood="chao" title={tr("company.pos_empty")} testId="pos-empty">{tr("company.pos_empty_hint")}</EmptyState>
      : <div className="tmDepts">{d.items.map((p: any) => <section key={p.id} className="ui-panel tm-card" data-testid={`pos-${p.id}`}>
        <div className="tm-card-head"><div><b>{p.title}</b><span>{p.department || tr("company.exec_board")}{p.reports_to ? ` · ${tr("company.reports_to")} ${p.reports_to}` : ""}</span></div>
          <span className={"ui-pill " + (p.vacancies ? "is-wait" : "is-ok")} data-testid={`pos-count-${p.id}`}>
            {p.filled}/{p.headcount}{p.vacancies ? ` · ${tr("company.n_vacant", {p0: p.vacancies})}` : ""}</span></div>
        {p.job_description && <small className="tmGuide">{p.job_description}</small>}
        {p.kpis.length > 0 && <ul className="cf-kpis">{p.kpis.map((k: any, i: number) => <li key={i}><b>{k.name}</b>{k.target != null ? `: ${k.target}${k.unit ? " " + k.unit : ""}` : ""} / {tr(`company.per_${k.period}` as Key)}</li>)}</ul>}
        <table className="ui-table"><tbody>
          {p.seats.map((s: any) => <tr key={s.member_id}><td><b>{s.name}</b> <small>{s.type === "agent" ? "AI" : tr("company.human")}</small></td>
            <td style={{textAlign: "right"}}>{can && <button className="ui-btn is-ghost is-sm" disabled={busy}
              onClick={() => run(() => apiCompany.unassign(p.id, s.member_id), tr("company.unassigned", {p0: s.name}))}>{tr("company.unassign")}</button>}</td></tr>)}
          {Array.from({length: p.vacancies}).map((_, i) => <tr key={"v" + i} className="cf-vacant"><td><small>{tr("company.vacant_seat")}</small></td>
            <td style={{textAlign: "right"}}>{can && i === 0 && d.unplaced.length > 0 && <select defaultValue="" disabled={busy} data-testid={`pos-assign-${p.id}`}
              onChange={e => e.target.value && run(() => apiCompany.assign(p.id, Number(e.target.value)), tr("company.assigned", {p0: p.title}))}>
              <option value="">{tr("company.assign_pick")}</option>
              {d.unplaced.map((m: any) => <option key={m.member_id} value={m.member_id}>{m.name}{m.role ? ` (${m.role})` : ""}</option>)}
            </select>}</td></tr>)}
        </tbody></table>
        {can && <div className="tmRow"><button className="ui-btn is-ghost is-sm" onClick={() => open(p)} data-testid={`pos-edit-${p.id}`}>{tr("company.edit")}</button>
          {!p.filled && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiCompany.archivePosition(p.id), tr("company.archived"))}>{tr("company.archive")}</button>}</div>}
      </section>)}</div>}
  </section>;
}

function PositionForm({edit, setEdit, depts, positions, tools, busy, onSave}: any) {
  const set = (k: string) => (e: any) => setEdit({...edit, [k]: e.target.value});
  const setK = (i: number, k: string, v: string) => setEdit({...edit, kpis: edit.kpis.map((x: any, j: number) => j === i ? {...x, [k]: v} : x)});
  return <section className="ui-panel tm-card cf-edit" data-testid="pos-form">
    <div className="tm-card-head"><div><b>{edit.id ? tr("company.edit_position") : tr("company.new_position")}</b><span>{tr("company.pos_compile_note")}</span></div></div>
    <div className="ui-form cf-form">
      <FormRow>
        <Field label={tr("company.title")}><input value={edit.title} onChange={set("title")} data-testid="pf-title"/></Field>
        <Field label={tr("company.department")}><select value={edit.department_id} onChange={set("department_id")}>
          <option value="">{tr("company.exec_board")}</option>{depts.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <Field label={tr("company.headcount")} hint={tr("company.headcount_hint")}><input type="number" min={0} max={500} value={edit.headcount} onChange={set("headcount")} data-testid="pf-headcount"/></Field>
      </FormRow>
      <Field label={tr("company.reports_to")}><select value={edit.reports_to_position_id} onChange={set("reports_to_position_id")}>
        <option value="">—</option>{positions.filter((p: any) => p.id !== edit.id).map((p: any) => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
      <Field label={tr("company.jd")}><textarea rows={3} value={edit.job_description} onChange={set("job_description")} data-testid="pf-jd"/></Field>
      <Field label={tr("company.responsibilities")} hint={tr("company.one_per_line")}><textarea rows={3} value={edit.responsibilities} onChange={set("responsibilities")}/></Field>
      <div className="ui-field"><span className="ui-field-label">{tr("company.kpis")}</span>
        {edit.kpis.map((k: any, i: number) => <div className="tmRow cf-kpi-row" key={i}>
          <input placeholder={tr("company.kpi_name")} value={k.name} onChange={e => setK(i, "name", e.target.value)} aria-label={tr("company.kpi_name")}/>
          <input type="number" placeholder={tr("company.kpi_target")} value={k.target} onChange={e => setK(i, "target", e.target.value)} aria-label={tr("company.kpi_target")} style={{width: 90}}/>
          <input placeholder={tr("company.kpi_unit")} value={k.unit} onChange={e => setK(i, "unit", e.target.value)} aria-label={tr("company.kpi_unit")} style={{width: 80}}/>
          <select value={k.period || "month"} onChange={e => setK(i, "period", e.target.value)} aria-label={tr("company.kpi_period")}>
            {["day", "week", "month", "quarter", "year"].map(x => <option key={x} value={x}>{tr(`company.per_${x}` as Key)}</option>)}</select>
          <button className="ui-btn is-ghost is-sm" onClick={() => setEdit({...edit, kpis: edit.kpis.filter((_: any, j: number) => j !== i)})} aria-label={tr("company.remove")}>×</button>
        </div>)}
        <button className="ui-btn is-ghost is-sm" onClick={() => setEdit({...edit, kpis: [...edit.kpis, {name: "", target: "", unit: "", period: "month"}]})} data-testid="pf-add-kpi">{tr("company.add_kpi")}</button>
      </div>
      <div className="ui-field"><span className="ui-field-label">{tr("company.tools")}</span><span className="ui-field-hint">{tr("company.tools_hint")}</span>
        <div className="cf-tools">{tools.map((n: string) => <label key={n} className="tmInline"><input type="checkbox" checked={edit.allowed_tools.includes(n)}
          onChange={e => setEdit({...edit, allowed_tools: e.target.checked ? [...edit.allowed_tools, n] : edit.allowed_tools.filter((x: string) => x !== n)})}/><code>{n}</code></label>)}</div></div>
      <Field label={tr("company.skills")} hint={tr("company.skills_hint")}><textarea rows={2} value={edit.allowed_skills} onChange={set("allowed_skills")}/></Field>
      <div className="tmRow"><button className="ui-btn is-primary" disabled={busy || !edit.title.trim()} onClick={onSave} data-testid="pf-save">{tr("company.save")}</button>
        <button className="ui-btn is-ghost" onClick={() => setEdit(null)}>{tr("company.cancel")}</button></div>
    </div>
  </section>;
}

// ===================================================================== Phân quyền

const EMPTY_RULE = {action_type: "refund", min_amount_usd: "", max_amount_usd: "", min_risk: "", approver_kind: "department_head",
  approver_position_id: "", agent_alone_level: "", note: ""};

export function AuthorityTab({companyId, chart, caps}: {companyId: number | null; chart: any; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => apiCompany.authority(companyId), [companyId]);
  const pos = useLoad(() => apiCompany.positions(companyId), [companyId]);
  const [edit, setEdit] = useState<any>(null), [busy, setBusy] = useState(false), [tpl, setTpl] = useState("");
  const [sim, setSim] = useState<any>({member_id: "", action_type: "refund", amount_usd: ""}), [simOut, setSimOut] = useState<any>(null);
  const toast = useToast();
  const can = !!caps?.manage_roles || !!caps?.create_company;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="auth-error"/>;
  if (!data) return <SkeletonRows n={5} h={44}/>;
  const d: any = data;
  const positions: any[] = (pos.data as any)?.items || [];
  const people: any[] = [];
  const walk = (ns: any[]) => ns?.forEach((n: any) => { people.push(n); walk(n.children); });
  walk(chart?.tree || []);
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(ok); await reload(); return r; } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function save() {
    const e = edit;
    const body: any = {action_type: e.action_type, min_amount_usd: e.min_amount_usd === "" ? null : Number(e.min_amount_usd),
      max_amount_usd: e.max_amount_usd === "" ? null : Number(e.max_amount_usd), min_risk: e.min_risk, approver_kind: e.approver_kind,
      approver_position_id: e.approver_kind === "position" && e.approver_position_id ? Number(e.approver_position_id) : null,
      agent_alone_level: e.agent_alone_level, note: e.note};
    const r = await run(() => e.id ? apiCompany.updateRule(e.id, body) : apiCompany.createRule({...body, company_id: companyId ?? d.company_id}), tr("company.rule_saved"));
    if (r) setEdit(null);
  }
  async function simulate() {
    setSimOut(null);
    try { setSimOut(await apiCompany.evaluate({member_id: Number(sim.member_id), action_type: sim.action_type, amount_usd: sim.amount_usd === "" ? null : Number(sim.amount_usd)})); }
    catch (e) { setSimOut({error: errorText(e)}); }
  }
  const set = (k: string) => (e: any) => setEdit({...edit, [k]: e.target.value});
  const byType: Record<string, any[]> = {};
  d.rules.forEach((r: any) => { (byType[r.action_type] ||= []).push(r); });
  return <section className="ui-section" data-testid="authority">
    <Notice testId="auth-explain">{tr("company.auth_explain")}</Notice>
    <div className="ui-toolbar">
      <div className="org-stats"><span><b>{d.rules.length}</b> {tr("company.rules")}</span><span>{tr("company.currency_usd")}</span></div>
      <span className="ui-grow"/>
      {can && <><select value={tpl} onChange={e => setTpl(e.target.value)} aria-label={tr("company.tpl_pick")}>
          <option value="">{tr("company.tpl_default")}</option><option value="shop">{tr("company.tpl_shop")}</option>
          <option value="agency">{tr("company.tpl_agency")}</option><option value="ketoan">{tr("company.tpl_ketoan")}</option></select>
        <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="auth-seed"
          onClick={() => (!d.rules.length || confirm(tr("company.replace_confirm"))) && run(() => apiCompany.seedDefaults({company_id: companyId ?? d.company_id, template: tpl || null, replace: d.rules.length > 0}), tr("company.seeded"))}>
          {d.rules.length ? tr("company.replace_defaults") : tr("company.use_defaults")}</button>
        <button className="ui-btn is-primary is-sm" onClick={() => setEdit({...EMPTY_RULE})} data-testid="auth-new">{tr("company.new_rule")}</button></>}
    </div>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    {edit && <section className="ui-panel tm-card cf-edit" data-testid="rule-form">
      <div className="tm-card-head"><div><b>{edit.id ? tr("company.edit_rule") : tr("company.new_rule")}</b><span>{tr("company.rule_hint")}</span></div></div>
      <div className="ui-form cf-form">
        <FormRow>
          <Field label={tr("company.action")}><select value={edit.action_type} onChange={set("action_type")} data-testid="rf-action">
            {d.action_types.map((a: any) => <option key={a.key} value={a.key}>{actLabel(a.key)}</option>)}</select></Field>
          <Field label={tr("company.from_usd")}><input type="number" min={0} value={edit.min_amount_usd} onChange={set("min_amount_usd")} data-testid="rf-min"/></Field>
          <Field label={tr("company.to_usd")} hint={tr("company.to_usd_hint")}><input type="number" min={0} value={edit.max_amount_usd} onChange={set("max_amount_usd")}/></Field>
        </FormRow>
        <FormRow>
          <Field label={tr("company.min_risk")}><select value={edit.min_risk} onChange={set("min_risk")}>
            <option value="">{tr("company.any_risk")}</option>{d.risks.map((r: string) => <option key={r} value={r}>{tr(`company.risk_${r}` as Key)}</option>)}</select></Field>
          <Field label={tr("company.approver")}><select value={edit.approver_kind} onChange={set("approver_kind")} data-testid="rf-approver">
            {d.approver_kinds.map((a: any) => <option key={a.key} value={a.key}>{whoLabel(a.key)}</option>)}</select></Field>
          {edit.approver_kind === "position" && <Field label={tr("company.approver_position")}><select value={edit.approver_position_id} onChange={set("approver_position_id")}>
            <option value="">{tr("company.choose")}</option>{positions.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>}
          <Field label={tr("company.agent_alone")} hint={tr("company.agent_alone_hint")}><select value={edit.agent_alone_level} onChange={set("agent_alone_level")}>
            {d.levels.map((l: any) => <option key={l.key} value={l.key}>{tr(`company.lvl_${l.key || "never"}` as Key)}</option>)}</select></Field>
        </FormRow>
        <Field label={tr("company.note")}><input value={edit.note} onChange={set("note")}/></Field>
        <div className="tmRow"><button className="ui-btn is-primary" disabled={busy} onClick={save} data-testid="rf-save">{tr("company.save")}</button>
          <button className="ui-btn is-ghost" onClick={() => setEdit(null)}>{tr("company.cancel")}</button></div>
      </div>
    </section>}
    {!d.rules.length ? <EmptyState mood="chao" title={tr("company.auth_empty")} testId="auth-empty">{tr("company.auth_empty_hint")}</EmptyState>
      : <section className="ui-panel"><table className="ui-table cf-matrix" data-testid="auth-table">
        <thead><tr><th>{tr("company.action")}</th><th>{tr("company.band")}</th><th>{tr("company.approver")}</th><th>{tr("company.agent_alone")}</th><th/></tr></thead>
        <tbody>{d.action_types.filter((a: any) => byType[a.key]).flatMap((a: any) => byType[a.key].map((r: any, i: number) =>
          <tr key={r.id} className={r.enabled ? "" : "is-off"} data-testid={`rule-${r.id}`}>
            <td>{i === 0 ? <b>{actLabel(a.key)}</b> : null}</td>
            <td>{a.money ? bandText(r.min_amount_usd, r.max_amount_usd) : "—"}{r.min_risk ? ` · ${tr("company.risk_from", {p0: tr(`company.risk_${r.min_risk}` as Key)})}` : ""}</td>
            <td>{r.approver_kind === "position" ? (positions.find(p => p.id === r.approver_position_id)?.title || whoLabel("position")) : whoLabel(r.approver_kind)}
              {r.note ? <><br/><small>{r.note}</small></> : null}</td>
            <td>{r.approver_kind === "none" ? "—" : tr(`company.lvl_${r.agent_alone_level || "never"}` as Key)}</td>
            <td style={{textAlign: "right", whiteSpace: "nowrap"}}><small className="cf-id">#{r.id}</small>{can && <>
              <button className="ui-btn is-ghost is-sm" onClick={() => setEdit({...r, min_amount_usd: r.min_amount_usd ?? "", max_amount_usd: r.max_amount_usd ?? "", approver_position_id: r.approver_position_id ?? ""})}>{tr("company.edit")}</button>
              <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiCompany.updateRule(r.id, {enabled: !r.enabled}), r.enabled ? tr("company.rule_off") : tr("company.rule_on"))}>{r.enabled ? tr("company.disable") : tr("company.enable")}</button>
              <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => confirm(tr("company.delete_confirm")) && run(() => apiCompany.deleteRule(r.id), tr("company.rule_deleted"))}>{tr("company.delete")}</button></>}</td>
          </tr>))}</tbody></table></section>}
    <section className="ui-panel tm-card" data-testid="auth-sim">
      <div className="tm-card-head"><div><b>{tr("company.sim_title")}</b><span>{tr("company.sim_desc")}</span></div></div>
      <div className="tmRow">
        <select value={sim.member_id} onChange={e => setSim({...sim, member_id: e.target.value})} aria-label={tr("company.sim_who")} data-testid="sim-who">
          <option value="">{tr("company.sim_who")}</option>{people.map(p => <option key={p.id} value={p.id}>{p.name}{p.type === "agent" ? " · AI" : ""}</option>)}</select>
        <select value={sim.action_type} onChange={e => setSim({...sim, action_type: e.target.value})} aria-label={tr("company.action")}>
          {d.action_types.map((a: any) => <option key={a.key} value={a.key}>{actLabel(a.key)}</option>)}</select>
        <input type="number" min={0} placeholder="USD" value={sim.amount_usd} onChange={e => setSim({...sim, amount_usd: e.target.value})} style={{width: 100}} aria-label="USD"/>
        <button className="ui-btn is-ghost is-sm" disabled={!sim.member_id} onClick={simulate} data-testid="sim-run">{tr("company.sim_run")}</button>
      </div>
      {simOut && <div className="tmResult" data-testid="sim-out">{simOut.error ? <span className="ui-inline-error">{simOut.error}</span>
        : !simOut.matched ? <span>{tr("company.sim_none")}</span>
        : <span><b>{tr("company.rule_n", {p0: simOut.rule_id})}</b> · {actLabel(simOut.action_type)} · {bandText(simOut.min_amount_usd, simOut.max_amount_usd)} → {simOut.approver_name || whoLabel(simOut.approver_kind)}.{" "}
            {simOut.requires_approval ? tr("company.sim_needs", {p0: simOut.approver_name || "—"}) : tr("company.sim_alone")}
            {simOut.notes?.length ? <small> ({simOut.notes.join(" ")})</small> : null}</span>}</div>}
    </section>
  </section>;
}
