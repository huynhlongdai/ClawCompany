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
    <div className="ui-grid is-3 nat-stats">
      <div className="ui-panel"><small>{tr("native.rules_active")}</small><b className="ui-num">{d.rules.filter((r: any) => r.enabled).length}</b></div>
      <div className="ui-panel"><small>{tr("native.violations_30d")}</small><b className="ui-num">{d.violations_30d}</b></div>
      <div className="ui-panel"><small>{tr("native.charter_enforced")}</small>
        <b className="ui-num">{d.prohibitions.filter((p: any) => p.enforced).length}/{d.prohibitions.length}</b></div>
    </div>

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
