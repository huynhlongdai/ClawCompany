"use client";
// P1 — Công ty › Kinh doanh: Khách hàng (M3g CRM), Dữ liệu cá nhân (đồng ý + yêu cầu chủ thể, Luật 91/2025 / NĐ 356/2025).
// Nhãn là mã i18n (crm.*); lỗi có mã từ backend → câu theo ngôn ngữ người dùng (biz.err_<mã>), không hiện câu tiếng Việt của backend.
import {useState} from "react";
import {apiBizContracts, apiCrm, apiDocs, apiMeetings} from "../lib/api";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {fmtDate, fmtDateTime, fmtMoney, t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

/** Lỗi có mã (detail.error) → câu i18n `biz.err_<mã>` nếu có, giữ nguyên các trường khác của ApiError. */
export function bizErr(e: any) {
  const code = e?.code || e?.detail?.error;
  if (code && e && typeof e === "object") {
    const key = `biz.err_${code}` as Key, s = tr(key, (e.detail || {}) as any);
    if (s !== key) { try { e.message = s; } catch { /* bỏ qua */ } }
  }
  return e;
}
export const lbl = (ns: string, v: string) => tr(`${ns}${v}` as Key);

// ------------------------------------------------------------------ Khách hàng

export function CustomersTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [q, setQ] = useState(""), [mk, setMk] = useState(false), [sel, setSel] = useState<number | null>(null), [adding, setAdding] = useState(false);
  const {data, error, reload, setError} = useLoad(() => companyId ? apiCrm.list(companyId, {q, consent: mk ? "marketing" : ""}) : Promise.resolve(null), [companyId, mk]);
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload} testId="crm-error"/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  return <section className="ui-section" data-testid="crm">
    {error ? <ErrorBanner error={bizErr(error)} onClose={() => setError(null)} testId="crm-save-error"/> : null}
    <p className="tmGuide">{tr("crm.explain")}</p>
    <div className="tmRow biz-wrap" data-testid="crm-stats">
      <span className="ui-pill">{tr("crm.total")}: <b>{d.counts.total}</b></span>
      <span className="ui-pill is-ok">{tr("crm.marketing_ok")}: <b>{d.counts.marketing_ok}</b></span>
      <span className={"ui-pill" + (d.counts.overdue_requests ? " is-risk" : d.counts.open_requests ? " is-wait" : "")}>{tr("crm.open_requests")}: <b>{d.counts.open_requests}</b></span>
      {d.pii_masked && <StatusPill tone="neutral">{tr("crm.pii_masked")}</StatusPill>}
      <span className="ui-grow"/>
      {can && <button className="ui-btn is-primary is-sm" onClick={() => { setAdding(!adding); setSel(null); }} data-testid="crm-new">{tr("crm.new")}</button>}
    </div>
    {adding && <NewContact companyId={companyId} meta={d} setError={(e: any) => setError(bizErr(e))} onDone={(c: any) => { setAdding(false); reload(); setSel(c.id); }} onCancel={() => setAdding(false)}/>}
    <div className="tmRow biz-wrap">
      <input className="ui-input" placeholder={tr("crm.search")} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && reload()} data-testid="crm-q"/>
      <label className="biz-check"><input type="checkbox" checked={mk} onChange={e => setMk(e.target.checked)}/> {tr("crm.only_marketing")}</label>
    </div>
    <div className="ui-panel"><table className="ui-table biz-table" data-testid="crm-table"><thead><tr>
      <th>{tr("crm.name")}</th><th className="biz-hide-m">{tr("crm.phone")}</th><th className="biz-hide-m">{tr("crm.segment")}</th><th>{tr("crm.consents")}</th></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={4}><EmptyState compact mood="chao" title={tr("crm.empty")}>{tr("crm.empty_hint")}</EmptyState></td></tr>
        : d.items.map((x: any) => <tr key={x.id} className={sel === x.id ? "is-selected" : ""} style={{cursor: "pointer"}} onClick={() => { setSel(x.id); setAdding(false); }} data-testid={`crm-row-${x.id}`}>
          <td><b>{x.name}</b>{x.org_name && <><br/><small>{x.org_name}</small></>}{x.status !== "active" && <> <StatusPill tone="risk">{lbl("crm.st_", x.status)}</StatusPill></>}</td>
          <td className="biz-hide-m biz-mono">{x.phone || "—"}</td>
          <td className="biz-hide-m">{x.segment || "—"}</td>
          <td>{x.consents.length === 0 ? <small>{tr("crm.no_consent")}</small> : x.consents.map((k: string) => {
            const [p, ch] = k.split(":"); return <span key={k} className={"ui-pill is-outline" + (p === "marketing" ? " is-ok" : "")}>{lbl("crm.p_", p)} · {lbl("crm.ch_", ch)}</span>; })}
            {x.open_requests > 0 && <> <StatusPill tone="wait">{tr("crm.req_open_n", {p0: x.open_requests})}</StatusPill></>}</td>
        </tr>)}</tbody></table></div>
    {sel && <ContactDetail id={sel} can={can} meta={d} onChanged={reload} onClose={() => setSel(null)}/>}
    <AgentPreview companyId={companyId} meta={d}/>
  </section>;
}

function NewContact({companyId, meta, setError, onDone, onCancel}: any) {
  const [f, setF] = useState<any>({name: "", kind: "person", phone: "", email: "", address: "", org_name: "", segment: "", department_id: ""});
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  async function save() {
    setSaving(true); setError(null);
    try { const r = await apiCrm.create({company_id: companyId, ...f, department_id: f.department_id ? Number(f.department_id) : null}); toast(tr("crm.created")); onDone(r); }
    catch (e) { setError(e); } finally { setSaving(false); }
  }
  return <section className="ui-panel tm-card" data-testid="crm-form">
    <fieldset className="ui-form" disabled={saving}>
      <FormRow>
        <Field label={tr("crm.name")}><input className="ui-input" value={f.name} onChange={set("name")} data-testid="crm-f-name"/></Field>
        <Field label={tr("crm.kind")}><select className="ui-input" value={f.kind} onChange={set("kind")}>
          <option value="person">{tr("crm.k_person")}</option><option value="business">{tr("crm.k_business")}</option></select></Field>
        <Field label={tr("crm.org_name")}><input className="ui-input" value={f.org_name} onChange={set("org_name")}/></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("crm.phone")}><input className="ui-input" inputMode="tel" value={f.phone} onChange={set("phone")} data-testid="crm-f-phone"/></Field>
        <Field label={tr("crm.email")}><input className="ui-input" inputMode="email" value={f.email} onChange={set("email")}/></Field>
        <Field label={tr("crm.segment")}><input className="ui-input" value={f.segment} onChange={set("segment")}/></Field>
        <Field label={tr("crm.department")}><select className="ui-input" value={f.department_id} onChange={set("department_id")}>
          <option value="">{tr("crm.dep_any")}</option>{(meta.departments || []).map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
      </FormRow>
      <Field label={tr("crm.address")}><input className="ui-input" value={f.address} onChange={set("address")}/></Field>
      <p><small>{tr("crm.form_hint")}</small></p>
      <div className="tmRow">
        <button className="ui-btn is-primary" disabled={!f.name.trim()} onClick={save} data-testid="crm-f-save">{tr("crm.save")}</button>
        <button className="ui-btn is-ghost" onClick={onCancel}>{tr("docs.cancel")}</button>
      </div>
    </fieldset>
  </section>;
}

function ContactDetail({id, can, meta, onChanged, onClose}: {id: number; can: boolean; meta: any; onChanged: () => void; onClose: () => void}) {
  const {data, error, reload, setError} = useLoad(() => apiCrm.get(id), [id]);
  const [cf, setCf] = useState({purpose: "marketing", channel: "zalo", evidence: "", notice_ref: ""});
  const [note, setNote] = useState(""), [rk, setRk] = useState("access"), [busy, setBusy] = useState(false), [msg, setMsg] = useState({purpose: "marketing", channel: "zalo", message: ""});
  const toast = useToast();
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={3} h={40}/>;
  const c: any = data;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(ok); await reload(); onChanged(); return r; } catch (e) { setError(bizErr(e)); await reload(); } finally { setBusy(false); }
  }
  const erased = c.status === "erased";
  return <section className="ui-panel tm-card" data-testid="crm-detail">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="crm-detail-error"/> : null}
    <div className="tmRow"><h3>{c.name}</h3><span className="ui-grow"/><button className="ui-btn is-ghost is-sm" onClick={onClose}>{tr("docs.close")}</button></div>
    <div className="tmRow biz-wrap">
      <span className="ui-pill">{tr("crm.phone")}: <b className="biz-mono">{c.phone || "—"}</b></span>
      <span className="ui-pill">{tr("crm.email")}: <b>{c.email || "—"}</b></span>
      {c.address && <span className="ui-pill">{tr("crm.address")}: <b>{c.address}</b></span>}
      <StatusPill tone={c.status === "active" ? "ok" : "risk"}>{lbl("crm.st_", c.status)}</StatusPill>
      {c.pii_masked && <StatusPill tone="neutral">{tr("crm.pii_masked")}</StatusPill>}
    </div>
    {c.notes && <p><small>{c.notes}</small></p>}

    <h4 className="ops-cat">{tr("crm.consent_title")}</h4>
    <p className="tmGuide">{tr("crm.consent_hint")}</p>
    <div className="ui-panel"><table className="ui-table biz-table" data-testid="crm-consents"><thead><tr>
      <th>{tr("crm.purpose")}</th><th>{tr("crm.channel")}</th><th className="biz-hide-m">{tr("crm.evidence")}</th><th>{tr("crm.status")}</th></tr></thead>
      <tbody>{c.consent_history.length === 0 ? <tr><td colSpan={4}><small>{tr("crm.no_consent")}</small></td></tr> : c.consent_history.map((x: any) => <tr key={x.id}>
        <td>{lbl("crm.p_", x.purpose)}</td><td>{lbl("crm.ch_", x.channel)}</td>
        <td className="biz-hide-m"><small>{x.evidence}{x.notice_ref ? ` · ${x.notice_ref}` : ""}<br/>{fmtDateTime(x.granted_at)}{x.recorded_by ? ` · ${x.recorded_by}` : ""}</small></td>
        <td>{x.status === "granted" ? <StatusPill tone="ok">{tr("crm.granted")}</StatusPill> : <StatusPill tone="neutral">{tr("crm.withdrawn_on", {p0: fmtDate(x.withdrawn_at)})}</StatusPill>}
          {can && x.status === "granted" && !erased && <> <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid={`crm-withdraw-${x.id}`}
            onClick={() => run(() => apiCrm.withdraw(x.id, note || tr("crm.withdraw_default")), tr("crm.withdrawn"))}>{tr("crm.withdraw")}</button></>}</td>
      </tr>)}</tbody></table></div>
    {can && !erased && <FormRow>
      <Field label={tr("crm.purpose")}><select className="ui-input" value={cf.purpose} onChange={e => setCf({...cf, purpose: e.target.value})} data-testid="crm-c-purpose">
        {meta.purposes.map((p: string) => <option key={p} value={p}>{lbl("crm.p_", p)}</option>)}</select></Field>
      <Field label={tr("crm.channel")}><select className="ui-input" value={cf.channel} onChange={e => setCf({...cf, channel: e.target.value})}>
        {meta.channels.map((p: string) => <option key={p} value={p}>{lbl("crm.ch_", p)}</option>)}</select></Field>
      <Field label={tr("crm.evidence")}><input className="ui-input" value={cf.evidence} placeholder={tr("crm.evidence_ph")} onChange={e => setCf({...cf, evidence: e.target.value})} data-testid="crm-c-evidence"/></Field>
      <Field label={tr("crm.notice_ref")}><input className="ui-input" value={cf.notice_ref} onChange={e => setCf({...cf, notice_ref: e.target.value})}/></Field>
      <Field label=" "><button className="ui-btn is-primary" disabled={busy} data-testid="crm-c-save"
        onClick={() => run(() => apiCrm.consent(c.id, cf), tr("crm.consent_saved")).then(() => setCf({...cf, evidence: ""}))}>{tr("crm.consent_add")}</button></Field>
    </FormRow>}

    {can && !erased && <><h4 className="ops-cat">{tr("crm.outreach_title")}</h4>
      <p className="tmGuide">{tr("crm.outreach_hint")}</p>
      <FormRow>
        <Field label={tr("crm.purpose")}><select className="ui-input" value={msg.purpose} onChange={e => setMsg({...msg, purpose: e.target.value})}>
          <option value="marketing">{lbl("crm.p_", "marketing")}</option><option value="service">{lbl("crm.p_", "service")}</option></select></Field>
        <Field label={tr("crm.channel")}><select className="ui-input" value={msg.channel} onChange={e => setMsg({...msg, channel: e.target.value})}>
          {meta.channels.map((p: string) => <option key={p} value={p}>{lbl("crm.ch_", p)}</option>)}</select></Field>
        <Field label={tr("crm.message")}><input className="ui-input" value={msg.message} onChange={e => setMsg({...msg, message: e.target.value})} data-testid="crm-o-msg"/></Field>
        <Field label=" "><button className="ui-btn is-ghost" disabled={busy || !msg.message.trim()} data-testid="crm-o-send"
          onClick={() => run(() => apiCrm.outreach(c.id, msg), tr("crm.outreach_ok"))}>{tr("crm.outreach_btn")}</button></Field>
      </FormRow></>}

    {can && !erased && <><h4 className="ops-cat">{tr("crm.req_title")}</h4>
      <div className="tmRow biz-wrap">
        <select className="ui-input" value={rk} onChange={e => setRk(e.target.value)} data-testid="crm-r-kind">
          {meta.dsr_kinds.map((k: string) => <option key={k} value={k}>{lbl("crm.dsr_", k)} ({tr("crm.n_days", {p0: meta.dsr_days[k]})})</option>)}</select>
        <input className="ui-input" placeholder={tr("crm.req_note")} value={note} onChange={e => setNote(e.target.value)}/>
        <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="crm-r-open"
          onClick={() => run(() => apiCrm.openRequest(c.id, {kind: rk, note}), tr("crm.req_opened"))}>{tr("crm.req_open")}</button>
      </div></>}
    {c.requests.length > 0 && <RequestTable items={c.requests} can={can} onDone={() => { reload(); onChanged(); }} setError={(e: any) => setError(bizErr(e))}/>}

    <h4 className="ops-cat">{tr("crm.history")}</h4>
    <ul className="biz-timeline" data-testid="crm-history">{c.interactions.length === 0 ? <li><small>{tr("crm.no_history")}</small></li>
      : c.interactions.map((i: any) => <li key={i.id}><small>{fmtDateTime(i.occurred_at)}{i.by ? ` · ${i.by}` : ""}</small>{" "}
        <StatusPill tone={i.kind === "outreach_blocked" ? "risk" : i.kind === "outreach" ? "ok" : "neutral"}>{lbl("crm.ik_", i.kind)}</StatusPill>{" "}
        {i.code ? interactionLine(i) : i.summary}{i.task_id ? <> · <a href={`/app/tasks/${i.task_id}`}>#{i.task_id}</a></> : null}</li>)}</ul>
  </section>;
}

function interactionLine(i: any): string {
  const p = i.params || {};
  if (i.code.startsWith("dsr_")) {
    const m = /^dsr_(opened|done)_(\w+)$/.exec(i.code);
    return m ? tr(`crm.ev_dsr_${m[1]}` as Key, {p0: lbl("crm.dsr_", m[2]), p1: p.request_id}) : tr(`crm.ev_${i.code}` as Key, {p0: p.request_id});
  }
  const base = tr(`crm.ev_${i.code}` as Key, {p0: p.purpose ? lbl("crm.p_", p.purpose) : "", p1: p.channel ? lbl("crm.ch_", p.channel) : ""});
  return i.summary ? `${base} — ${i.summary}` : base;
}

function RequestTable({items, can, onDone, setError}: {items: any[]; can: boolean; onDone: () => void; setError: (e: any) => void}) {
  const [busy, setBusy] = useState(false), [reason, setReason] = useState("");
  const toast = useToast();
  async function act(r: any, action: string) {
    setBusy(true); setError(null);
    try { await apiCrm.act(r.id, {action, note: reason}); toast(tr("crm.req_saved")); setReason(""); onDone(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <div className="ui-panel"><table className="ui-table biz-table" data-testid="crm-requests"><thead><tr>
    <th>{tr("crm.req_kind")}</th><th>{tr("crm.req_due")}</th><th>{tr("crm.status")}</th>{can && <th/>}</tr></thead>
    <tbody>{items.map(r => { const open = r.status === "open" || r.status === "in_progress"; return <tr key={r.id} data-testid={`crm-req-${r.id}`}>
      <td><b>#{r.id}</b> {lbl("crm.dsr_", r.kind)}{r.contact_name ? <><br/><small>{r.contact_name}</small></> : null}</td>
      <td><small>{tr("crm.ack_by", {p0: fmtDateTime(r.ack_due_at)})}{r.ack_overdue && <> <StatusPill tone="risk">{tr("crm.overdue")}</StatusPill></>}<br/>
        {tr("crm.do_by", {p0: fmtDate(r.due_at), p1: r.days_allowed})}{r.overdue && <> <StatusPill tone="risk">{tr("crm.overdue")}</StatusPill></>}</small></td>
      <td><StatusPill tone={r.status === "done" ? "ok" : r.status === "rejected" ? "neutral" : "wait"}>{lbl("crm.rs_", r.status)}</StatusPill>
        {r.evidence?.export_sha256 && <><br/><small className="biz-mono">sha256 {r.evidence.export_sha256.slice(0, 12)}…</small></>}
        {r.evidence?.pre_erase_sha256 && <><br/><small className="biz-mono">{tr("crm.erased_hash")} {r.evidence.pre_erase_sha256.slice(0, 12)}…</small></>}</td>
      {can && <td>{open && <div className="tmRow biz-wrap">
        {!r.acknowledged_at && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => act(r, "ack")} data-testid={`crm-req-ack-${r.id}`}>{tr("crm.req_ack")}</button>}
        <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => act(r, "complete")} data-testid={`crm-req-done-${r.id}`}>{r.kind === "delete" ? tr("crm.req_erase") : tr("crm.req_complete")}</button>
        <input className="ui-input" placeholder={tr("crm.reject_reason")} value={reason} onChange={e => setReason(e.target.value)} style={{maxWidth: 160}}/>
        <button className="ui-btn is-ghost is-sm" disabled={busy || reason.trim().length < 5} onClick={() => act(r, "reject")}>{tr("crm.req_reject")}</button>
      </div>}</td>}
    </tr>; })}</tbody></table></div>;
}

function AgentPreview({companyId, meta}: {companyId: number; meta: any}) {
  const [q, setQ] = useState(""), [dep, setDep] = useState(""), [res, setRes] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  async function go() { setErr(null); try { setRes(await apiCrm.preview(companyId, q, dep ? Number(dep) : null)); } catch (e) { setErr(bizErr(e)); } }
  return <div className="ui-panel tm-card" data-testid="crm-preview">
    <h4 className="ops-cat">{tr("crm.preview")}</h4>
    <p className="tmGuide">{tr("crm.preview_hint")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)}/> : null}
    <div className="tmRow biz-wrap">
      <select className="ui-input" value={dep} onChange={e => setDep(e.target.value)}><option value="">{tr("crm.dep_none")}</option>
        {(meta.departments || []).map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      <input className="ui-input" value={q} placeholder={tr("crm.preview_ph")} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && go()} data-testid="crm-preview-q"/>
      <button className="ui-btn is-ghost is-sm" onClick={go} data-testid="crm-preview-go">{tr("crm.preview_go")}</button>
    </div>
    {res && <><ul className="cat-preview" data-testid="crm-preview-out">{res.contacts.length === 0 ? <li><small>{tr("crm.preview_none")}</small></li>
      : res.contacts.map((x: any) => <li key={x.contact_id}><b>{x.name}</b> <span className="biz-mono">{x.phone || "—"}</span> · {x.email || "—"}
        {x.marketing_allowed_channels.length > 0 && <><br/><small>{tr("crm.preview_mk", {p0: x.marketing_allowed_channels.map((c: string) => lbl("crm.ch_", c)).join(", ")})}</small></>}</li>)}</ul>
      {res.hidden_without_consent ? <p><small>{tr("crm.preview_hidden", {p0: res.hidden_without_consent})}</small></p> : null}</>}
  </div>;
}

// ------------------------------------------------------------------ Dữ liệu cá nhân (yêu cầu của chủ thể)

export function PrivacyTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [st, setSt] = useState("open");
  const {data, error, reload, setError} = useLoad(() => companyId ? apiCrm.requests(companyId, st) : Promise.resolve(null), [companyId, st]);
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={4} h={40}/>;
  const d: any = data;
  return <section className="ui-section" data-testid="privacy">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("crm.privacy_explain")}</p>
    <div className="ui-banner" data-testid="privacy-deadlines"><div>
      <b>{tr("crm.deadlines_title")}</b><br/>
      <small>{tr("crm.deadlines_line", {p0: d.ack_working_days, p1: d.days.access, p2: d.days.withdraw, p3: d.days.delete})}</small><br/>
      <small>{tr("crm.legal_note")}</small></div></div>
    <div className="tmRow biz-wrap">
      {["open", "done", "rejected", ""].map(s => <button key={s || "all"} className={"ui-btn is-sm " + (st === s ? "is-primary" : "is-ghost")} onClick={() => setSt(s)}>{s ? lbl("crm.rs_", s === "open" ? "open" : s) : tr("crm.all")}</button>)}
    </div>
    {d.items.length === 0 ? <EmptyState compact mood="duyet-xong" title={tr("crm.req_empty")}>{tr("crm.req_empty_hint")}</EmptyState>
      : <RequestTable items={d.items} can={can} onDone={reload} setError={(e: any) => setError(bizErr(e))}/>}
  </section>;
}

// ------------------------------------------------------------------ Hợp đồng & đối tác (M3h)

const CT_TONE: Record<string, any> = {draft: "neutral", pending: "wait", active: "ok", expired: "neutral", terminated: "risk", rejected: "risk"};

export function PartnersTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [st, setSt] = useState(""), [sel, setSel] = useState<number | null>(null), [adding, setAdding] = useState<"" | "contract" | "partner">("");
  const {data, error, reload, setError} = useLoad(() => companyId ? apiBizContracts.list(companyId, {status: st}) : Promise.resolve(null), [companyId, st]);
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  return <section className="ui-section" data-testid="contracts">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("ct.explain", {p0: d.remind_days})}</p>
    <div className="tmRow biz-wrap" data-testid="ct-stats">
      <span className="ui-pill">{tr("ct.total")}: <b>{d.counts.total}</b></span>
      <span className="ui-pill is-ok">{tr("ct.active")}: <b>{d.counts.active}</b></span>
      <span className={"ui-pill" + (d.counts.pending ? " is-wait" : "")}>{tr("ct.pending")}: <b>{d.counts.pending}</b></span>
      <span className={"ui-pill" + (d.counts.due_soon ? " is-risk" : "")}>{tr("ct.due_soon")}: <b>{d.counts.due_soon}</b></span>
      <span className="ui-grow"/>
      {can && <><button className="ui-btn is-primary is-sm" onClick={() => setAdding(adding === "contract" ? "" : "contract")} data-testid="ct-new">{tr("ct.new")}</button>
        <button className="ui-btn is-ghost is-sm" onClick={() => setAdding(adding === "partner" ? "" : "partner")} data-testid="pt-new">{tr("ct.new_partner")}</button></>}
    </div>
    {adding === "partner" && <NewPartner companyId={companyId} kinds={d.partner_kinds} setError={(e: any) => setError(bizErr(e))} onDone={() => { setAdding(""); reload(); }}/>}
    {adding === "contract" && <NewContract companyId={companyId} meta={d} setError={(e: any) => setError(bizErr(e))} onDone={(c: any) => { setAdding(""); reload(); setSel(c.id); }}/>}
    <div className="tmRow biz-wrap">{["", "active", "pending", "draft", "expired"].map(s => <button key={s || "all"} className={"ui-btn is-sm " + (st === s ? "is-primary" : "is-ghost")} onClick={() => setSt(s)}>{s ? lbl("ct.st_", s) : tr("crm.all")}</button>)}</div>
    <div className="ui-panel"><table className="ui-table biz-table" data-testid="ct-table"><thead><tr>
      <th>{tr("ct.contract")}</th><th className="biz-hide-m">{tr("ct.value")}</th><th>{tr("ct.dates")}</th><th>{tr("crm.status")}</th></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={4}><EmptyState compact mood="chao" title={tr("ct.empty")}>{tr("ct.empty_hint")}</EmptyState></td></tr>
        : d.items.map((x: any) => <tr key={x.id} className={sel === x.id ? "is-selected" : ""} style={{cursor: "pointer"}} onClick={() => setSel(x.id)} data-testid={`ct-row-${x.id}`}>
          <td><code className="doc-code">{x.code}</code> <b>{x.title}</b><br/><small>{x.partner?.name || "—"} · {lbl("ct.k_", x.kind)}</small></td>
          <td className="biz-hide-m biz-num">{x.value_amount != null ? fmtMoney(x.value_amount, x.currency) : "—"}</td>
          <td><small>{fmtDate(x.start_date)} → {x.end_date ? fmtDate(x.end_date) : "…"}{x.auto_renew && <> · {tr("ct.auto_renew_short")}</>}
            {x.status === "active" && x.days_to_notice != null && x.days_to_notice >= 0 && x.days_to_notice <= d.remind_days && <><br/><StatusPill tone="risk">{tr("ct.notice_in", {p0: x.days_to_notice})}</StatusPill></>}
            {x.status === "active" && x.days_to_end != null && x.days_to_end >= 0 && x.days_to_end <= d.remind_days && <><br/><StatusPill tone="wait">{tr("ct.end_in", {p0: x.days_to_end})}</StatusPill></>}</small></td>
          <td><StatusPill tone={CT_TONE[x.status]}>{lbl("ct.st_", x.status)}</StatusPill></td>
        </tr>)}</tbody></table></div>
    {sel && <ContractDetail id={sel} can={can} onChanged={reload} onClose={() => setSel(null)}/>}
    <h4 className="ops-cat">{tr("ct.partners")}</h4>
    <div className="ui-panel"><table className="ui-table biz-table" data-testid="pt-table"><thead><tr>
      <th>{tr("crm.name")}</th><th className="biz-hide-m">{tr("ct.tax_code")}</th><th className="biz-hide-m">{tr("ct.contact")}</th><th>{tr("ct.active")}</th></tr></thead>
      <tbody>{d.partners.length === 0 ? <tr><td colSpan={4}><small>{tr("ct.no_partners")}</small></td></tr> : d.partners.map((p: any) => <tr key={p.id}>
        <td><b>{p.name}</b><br/><small>{lbl("ct.pk_", p.kind)}{p.rating ? ` · ${"★".repeat(p.rating)}` : ""}</small></td>
        <td className="biz-hide-m biz-mono">{p.tax_code || "—"}</td><td className="biz-hide-m"><small>{[p.contact_person, p.phone, p.email].filter(Boolean).join(" · ") || "—"}</small></td>
        <td>{p.active_contracts}</td></tr>)}</tbody></table></div>
    <ContractPreview companyId={companyId}/>
  </section>;
}

function NewPartner({companyId, kinds, setError, onDone}: any) {
  const [f, setF] = useState<any>({name: "", kind: "supplier", tax_code: "", contact_person: "", phone: "", email: ""});
  const toast = useToast();
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  return <section className="ui-panel tm-card" data-testid="pt-form"><FormRow>
    <Field label={tr("crm.name")}><input className="ui-input" value={f.name} onChange={set("name")} data-testid="pt-f-name"/></Field>
    <Field label={tr("crm.kind")}><select className="ui-input" value={f.kind} onChange={set("kind")}>{kinds.map((k: string) => <option key={k} value={k}>{lbl("ct.pk_", k)}</option>)}</select></Field>
    <Field label={tr("ct.tax_code")}><input className="ui-input" inputMode="numeric" value={f.tax_code} onChange={set("tax_code")}/></Field>
  </FormRow><FormRow>
    <Field label={tr("ct.contact")}><input className="ui-input" value={f.contact_person} onChange={set("contact_person")}/></Field>
    <Field label={tr("crm.phone")}><input className="ui-input" value={f.phone} onChange={set("phone")}/></Field>
    <Field label={tr("crm.email")}><input className="ui-input" value={f.email} onChange={set("email")}/></Field>
  </FormRow>
    <button className="ui-btn is-primary" disabled={!f.name.trim()} data-testid="pt-f-save"
      onClick={async () => { setError(null); try { await apiBizContracts.createPartner({company_id: companyId, ...f}); toast(tr("ct.partner_saved")); onDone(); } catch (e) { setError(e); } }}>{tr("crm.save")}</button>
  </section>;
}

function NewContract({companyId, meta, setError, onDone}: any) {
  const [f, setF] = useState<any>({title: "", kind: "purchase", partner_id: "", value_amount: "", currency: "VND", start_date: "", end_date: "", notice_days: "", auto_renew: false,
    delivery_days: "", response_hours: "", payment_days: "", key_terms: ""});
  const toast = useToast();
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});
  async function save() {
    setError(null);
    const sla: any = {};
    for (const k of ["delivery_days", "response_hours", "payment_days"]) if (f[k] !== "") sla[k] = Number(f[k]);
    try {
      const r = await apiBizContracts.create({company_id: companyId, title: f.title, kind: f.kind, partner_id: f.partner_id ? Number(f.partner_id) : null,
        value_amount: f.value_amount || null, currency: f.currency, start_date: f.start_date || null, end_date: f.end_date || null,
        notice_days: f.notice_days || null, auto_renew: f.auto_renew, sla, key_terms: f.key_terms});
      toast(tr("ct.saved")); onDone(r);
    } catch (e) { setError(e); }
  }
  return <section className="ui-panel tm-card" data-testid="ct-form"><FormRow>
    <Field label={tr("ct.title")}><input className="ui-input" value={f.title} onChange={set("title")} data-testid="ct-f-title"/></Field>
    <Field label={tr("crm.kind")}><select className="ui-input" value={f.kind} onChange={set("kind")}>{meta.kinds.map((k: string) => <option key={k} value={k}>{lbl("ct.k_", k)}</option>)}</select></Field>
    <Field label={tr("ct.partner")}><select className="ui-input" value={f.partner_id} onChange={set("partner_id")} data-testid="ct-f-partner"><option value="">—</option>
      {meta.partners.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
  </FormRow><FormRow>
    <Field label={tr("ct.value")}><input className="ui-input" inputMode="numeric" value={f.value_amount} onChange={set("value_amount")} placeholder="120000000"/></Field>
    <Field label={tr("cat.currency")}><select className="ui-input" value={f.currency} onChange={set("currency")}><option>VND</option><option>USD</option></select></Field>
    <Field label={tr("ct.start")}><input className="ui-input" type="date" value={f.start_date} onChange={set("start_date")}/></Field>
    <Field label={tr("ct.end")}><input className="ui-input" type="date" value={f.end_date} onChange={set("end_date")}/></Field>
  </FormRow><FormRow>
    <Field label={tr("ct.notice_days")}><input className="ui-input" inputMode="numeric" value={f.notice_days} onChange={set("notice_days")}/></Field>
    <Field label={tr("ct.sla_delivery")}><input className="ui-input" inputMode="numeric" value={f.delivery_days} onChange={set("delivery_days")}/></Field>
    <Field label={tr("ct.sla_response")}><input className="ui-input" inputMode="numeric" value={f.response_hours} onChange={set("response_hours")}/></Field>
    <Field label={tr("ct.sla_payment")}><input className="ui-input" inputMode="numeric" value={f.payment_days} onChange={set("payment_days")}/></Field>
  </FormRow>
    <label className="biz-check"><input type="checkbox" checked={f.auto_renew} onChange={set("auto_renew")}/> {tr("ct.auto_renew")}</label>
    <Field label={tr("ct.key_terms")}><textarea className="ui-input" rows={3} value={f.key_terms} onChange={set("key_terms")}/></Field>
    <button className="ui-btn is-primary" disabled={!f.title.trim()} onClick={save} data-testid="ct-f-save">{tr("ct.save_draft")}</button>
  </section>;
}

function ContractDetail({id, can, onChanged, onClose}: {id: number; can: boolean; onChanged: () => void; onClose: () => void}) {
  const {data, error, reload, setError} = useLoad(() => apiBizContracts.get(id), [id]);
  const docs = useLoad(() => data ? apiDocs.list((data as any).company_id, {}) : Promise.resolve(null), [(data as any)?.company_id]);
  const [note, setNote] = useState(""), [busy, setBusy] = useState(false);
  const toast = useToast();
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={3} h={40}/>;
  const c: any = data;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); await reload(); onChanged(); } catch (e) { setError(bizErr(e)); } finally { setBusy(false); }
  }
  const sla = Object.entries(c.sla || {});
  return <section className="ui-panel tm-card" data-testid="ct-detail">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <div className="tmRow"><h3><code className="doc-code">{c.code}</code> {c.title}</h3><span className="ui-grow"/><button className="ui-btn is-ghost is-sm" onClick={onClose}>{tr("docs.close")}</button></div>
    <div className="tmRow biz-wrap">
      <StatusPill tone={CT_TONE[c.status]}>{lbl("ct.st_", c.status)}</StatusPill>
      <span className="ui-pill">{tr("ct.partner")}: <b>{c.partner?.name || "—"}</b></span>
      <span className="ui-pill">{tr("ct.value")}: <b className="biz-num">{c.value_amount != null ? fmtMoney(c.value_amount, c.currency) : "—"}</b></span>
      <span className="ui-pill">{fmtDate(c.start_date)} → {c.end_date ? fmtDate(c.end_date) : "…"}</span>
      {c.notice_deadline && <span className="ui-pill">{tr("ct.notice_deadline")}: <b>{fmtDate(c.notice_deadline)}</b></span>}
      {c.auto_renew && <span className="ui-pill">{tr("ct.auto_renew_n", {p0: c.renewal_months})}</span>}
      {c.approver && <span className="ui-pill">{tr("ct.signer")}: <b>{c.approver}</b></span>}
    </div>
    {sla.length > 0 && <p><small>{tr("ct.sla")}: {sla.map(([k, v]: any) => `${lbl("ct.sla_k_", k)} ${v}`).join(" · ")}</small></p>}
    {c.key_terms && <p className="tmGuide">{c.key_terms}</p>}
    {c.review_note && <p><small>{tr("ct.review_note")}: {c.review_note}</small></p>}
    {c.locked && <p><small>{tr("ct.locked_hint")}</small></p>}
    {can && <div className="tmRow biz-wrap">
      <select className="ui-input" value={c.document?.id || ""} data-testid="ct-doc-pick" onChange={e => run(() => apiBizContracts.patch(c.id, {document_id: e.target.value ? Number(e.target.value) : null}), tr("docs.saved"))}>
        <option value="">{tr("ct.doc_pick")}</option>{((docs.data as any)?.items || []).map((x: any) => <option key={x.id} value={x.id}>{x.doc_code} · {x.title}</option>)}</select>
      {(c.status === "draft" || c.status === "rejected") && <button className="ui-btn is-primary is-sm" disabled={busy} data-testid="ct-submit" onClick={() => run(() => apiBizContracts.submit(c.id), tr("ct.submitted"))}>{tr("ct.submit")}</button>}
      {c.status === "pending" && <><input className="ui-input" placeholder={tr("cat.decide_note")} value={note} onChange={e => setNote(e.target.value)}/>
        <button className="ui-btn is-primary is-sm" disabled={busy} data-testid="ct-approve" onClick={() => run(() => apiBizContracts.decide(c.id, "approved", note), tr("ct.signed"))}>{tr("ct.approve")}</button>
        <button className="ui-btn is-ghost is-sm" disabled={busy || !note.trim()} onClick={() => run(() => apiBizContracts.decide(c.id, "rejected", note), tr("cat.rejected"))}>{tr("cat.reject")}</button></>}
      {c.status === "active" && <><input className="ui-input" placeholder={tr("ct.terminate_reason")} value={note} onChange={e => setNote(e.target.value)}/>
        <button className="ui-btn is-ghost is-sm" disabled={busy || note.trim().length < 5} onClick={() => run(() => apiBizContracts.terminate(c.id, note), tr("ct.terminated"))}>{tr("ct.terminate")}</button></>}
    </div>}
    {c.document && <p><small>{tr("ct.signed_doc")}: <code className="doc-code">{c.document.doc_code}</code> {c.document.title}</small></p>}
    <h4 className="ops-cat">{tr("crm.history")}</h4>
    <ul className="biz-timeline">{(c.history || []).map((h: any, i: number) => <li key={i}><small>{fmtDateTime(h.at)}{h.by ? ` · ${h.by}` : ""}</small> {lbl("ct.ev_", h.type.replace("contract.", ""))}</li>)}</ul>
  </section>;
}

function ContractPreview({companyId}: {companyId: number}) {
  const [q, setQ] = useState(""), [res, setRes] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  return <div className="ui-panel tm-card" data-testid="ct-preview">
    <h4 className="ops-cat">{tr("crm.preview")}</h4><p className="tmGuide">{tr("ct.preview_hint")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)}/> : null}
    <div className="tmRow biz-wrap"><input className="ui-input" value={q} placeholder={tr("ct.preview_ph")} onChange={e => setQ(e.target.value)} data-testid="ct-preview-q"/>
      <button className="ui-btn is-ghost is-sm" onClick={async () => { setErr(null); try { setRes(await apiBizContracts.preview(companyId, q)); } catch (e) { setErr(bizErr(e)); } }} data-testid="ct-preview-go">{tr("crm.preview_go")}</button></div>
    {res && <ul className="cat-preview">{res.contracts.length === 0 ? <li><small>{tr("ct.preview_none")}</small></li> : res.contracts.map((x: any) => <li key={x.code}>
      <code className="doc-code">{x.code}</code> <b>{x.title}</b> — {x.partner}<br/><small>{Object.entries(x.sla || {}).map(([k, v]: any) => `${lbl("ct.sla_k_", k)} ${v}`).join(" · ") || tr("ct.no_sla")}</small></li>)}</ul>}
  </div>;
}

// ------------------------------------------------------------------ Họp & quyết định (M3i)

const MS_TONE: Record<string, any> = {draft: "neutral", in_review: "wait", approved: "ok"};
const DS_TONE: Record<string, any> = {decided: "ok", superseded: "neutral", revoked: "risk"};

export function MeetingsTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [sel, setSel] = useState<number | null>(null), [adding, setAdding] = useState<"" | "meeting" | "decision">("");
  const {data, error, reload, setError} = useLoad(() => companyId ? apiMeetings.list(companyId) : Promise.resolve(null), [companyId]);
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  return <section className="ui-section" data-testid="meetings">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("mt.explain")}</p>
    <div className="tmRow biz-wrap" data-testid="mt-stats">
      <span className="ui-pill">{tr("mt.meetings")}: <b>{d.counts.meetings}</b></span>
      <span className="ui-pill is-ok">{tr("mt.in_effect")}: <b>{d.counts.decisions_in_effect}</b></span>
      <span className={"ui-pill" + (d.counts.open_actions ? " is-wait" : "")}>{tr("mt.open_actions")}: <b>{d.counts.open_actions}</b></span>
      <span className={"ui-pill" + (d.counts.pending_minutes ? " is-wait" : "")}>{tr("mt.pending_minutes")}: <b>{d.counts.pending_minutes}</b></span>
      <span className="ui-grow"/>
      {can && <><button className="ui-btn is-primary is-sm" onClick={() => setAdding(adding === "meeting" ? "" : "meeting")} data-testid="mt-new">{tr("mt.new")}</button>
        <button className="ui-btn is-ghost is-sm" onClick={() => setAdding(adding === "decision" ? "" : "decision")} data-testid="dc-new">{tr("mt.new_decision")}</button></>}
    </div>
    {adding === "meeting" && <NewMeeting companyId={companyId} meta={d} setError={(e: any) => setError(bizErr(e))} onDone={(m: any) => { setAdding(""); reload(); setSel(m.id); }}/>}
    {adding === "decision" && <DecisionForm companyId={companyId} meta={d} setError={(e: any) => setError(bizErr(e))} onDone={() => { setAdding(""); reload(); }}/>}
    <div className="ui-panel"><table className="ui-table biz-table" data-testid="mt-table"><thead><tr>
      <th>{tr("mt.meeting")}</th><th>{tr("mt.when")}</th><th className="biz-hide-m">{tr("mt.counts")}</th><th>{tr("crm.status")}</th></tr></thead>
      <tbody>{d.meetings.length === 0 ? <tr><td colSpan={4}><EmptyState compact mood="chao" title={tr("mt.empty")}>{tr("mt.empty_hint")}</EmptyState></td></tr>
        : d.meetings.map((m: any) => <tr key={m.id} className={sel === m.id ? "is-selected" : ""} style={{cursor: "pointer"}} onClick={() => setSel(m.id)} data-testid={`mt-row-${m.id}`}>
          <td><b>{m.title}</b><br/><small>{lbl("mt.k_", m.kind)}{m.chair ? ` · ${m.chair}` : ""}</small></td>
          <td><small>{fmtDateTime(m.held_at)}</small></td>
          <td className="biz-hide-m"><small>{tr("mt.n_dec_act", {p0: m.n_decisions, p1: m.n_actions})}</small></td>
          <td><StatusPill tone={MS_TONE[m.status]}>{lbl("mt.ms_", m.status)}</StatusPill></td></tr>)}</tbody></table></div>
    {sel && <MeetingDetail id={sel} can={can} meta={d} onChanged={reload} onClose={() => setSel(null)}/>}
    <h4 className="ops-cat">{tr("mt.decision_log")}</h4>
    <div className="ui-panel"><table className="ui-table biz-table" data-testid="dc-table"><thead><tr>
      <th>{tr("mt.decision")}</th><th className="biz-hide-m">{tr("mt.basis")}</th><th>{tr("mt.effective")}</th><th>{tr("crm.status")}</th></tr></thead>
      <tbody>{d.decisions.length === 0 ? <tr><td colSpan={4}><small>{tr("mt.no_decisions")}</small></td></tr> : d.decisions.map((x: any) => <tr key={x.id}>
        <td><code className="doc-code">{x.number}</code> <b>{x.title}</b><br/><small>{x.body}</small>{!x.agent_visible && <> <StatusPill tone="neutral">{tr("mt.hidden_agents")}</StatusPill></>}</td>
        <td className="biz-hide-m"><small>{x.decided_by ? `${x.decided_by} · ` : ""}{x.authority_basis}</small></td>
        <td><small>{fmtDate(x.effective_from)}{x.effective_to ? ` → ${fmtDate(x.effective_to)}` : ""}</small></td>
        <td><StatusPill tone={DS_TONE[x.status] || "neutral"}>{lbl("mt.ds_", x.status)}</StatusPill>
          {can && x.status === "decided" && <RevokeBtn id={x.id} onDone={reload} setError={(e: any) => setError(bizErr(e))}/>}</td></tr>)}</tbody></table></div>
    <DecisionPreview companyId={companyId}/>
  </section>;
}

function RevokeBtn({id, onDone, setError}: any) {
  const [open, setOpen] = useState(false), [note, setNote] = useState("");
  if (!open) return <> <button className="ui-btn is-ghost is-sm" onClick={() => setOpen(true)}>{tr("mt.revoke")}</button></>;
  return <div className="tmRow biz-wrap"><input className="ui-input" placeholder={tr("mt.revoke_reason")} value={note} onChange={e => setNote(e.target.value)}/>
    <button className="ui-btn is-ghost is-sm" disabled={note.trim().length < 5} onClick={async () => { setError(null); try { await apiMeetings.revoke(id, note); onDone(); } catch (e) { setError(e); } }}>{tr("mt.revoke")}</button></div>;
}

function NewMeeting({companyId, meta, setError, onDone}: any) {
  const [f, setF] = useState<any>({title: "", kind: "weekly", held_at: "", location: "", attendee_ids: [] as number[], agenda: "", rhythm_report_id: ""});
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  const humans = meta.members.filter((m: any) => m.type === "human");
  return <section className="ui-panel tm-card" data-testid="mt-form"><FormRow>
    <Field label={tr("mt.title")}><input className="ui-input" value={f.title} onChange={set("title")} data-testid="mt-f-title"/></Field>
    <Field label={tr("crm.kind")}><select className="ui-input" value={f.kind} onChange={set("kind")}>{meta.kinds.map((k: string) => <option key={k} value={k}>{lbl("mt.k_", k)}</option>)}</select></Field>
    <Field label={tr("mt.when")}><input className="ui-input" type="datetime-local" value={f.held_at} onChange={set("held_at")}/></Field>
    <Field label={tr("mt.location")}><input className="ui-input" value={f.location} onChange={set("location")}/></Field>
  </FormRow>
    <Field label={tr("mt.attendees")}><div className="tmRow biz-wrap">{humans.map((m: any) => <label key={m.id} className="biz-check">
      <input type="checkbox" checked={f.attendee_ids.includes(m.id)} onChange={e => setF({...f, attendee_ids: e.target.checked ? [...f.attendee_ids, m.id] : f.attendee_ids.filter((x: number) => x !== m.id)})}/> {m.name}</label>)}</div></Field>
    <Field label={tr("mt.agenda")}><textarea className="ui-input" rows={3} value={f.agenda} onChange={set("agenda")}/></Field>
    {meta.rhythm_reports.length > 0 && <Field label={tr("mt.link_report")}><select className="ui-input" value={f.rhythm_report_id} onChange={set("rhythm_report_id")}><option value="">—</option>
      {meta.rhythm_reports.map((r: any) => <option key={r.id} value={r.id}>{lbl("mt.rk_", r.kind)} {r.period_key}</option>)}</select></Field>}
    <button className="ui-btn is-primary" disabled={!f.title.trim()} data-testid="mt-f-save" onClick={async () => { setError(null); try {
      const held = f.held_at ? new Date(f.held_at).toISOString().slice(0, 19) : undefined;
      onDone(await apiMeetings.create({company_id: companyId, ...f, held_at: held, rhythm_report_id: f.rhythm_report_id ? Number(f.rhythm_report_id) : null})); } catch (e) { setError(e); } }}>{tr("crm.save")}</button>
  </section>;
}

function DecisionForm({companyId, meta, meetingId, setError, onDone}: any) {
  const [f, setF] = useState<any>({title: "", body: "", authority_basis: "", action_type: "", decided_by_member_id: "", effective_from: "", agent_visible: true});
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value});
  const toast = useToast();
  return <section className="ui-panel tm-card" data-testid="dc-form"><FormRow>
    <Field label={tr("mt.decision")}><input className="ui-input" value={f.title} onChange={set("title")} data-testid="dc-f-title"/></Field>
    <Field label={tr("mt.decided_by")}><select className="ui-input" value={f.decided_by_member_id} onChange={set("decided_by_member_id")}><option value="">{tr("mt.me")}</option>
      {meta.members.filter((m: any) => m.type === "human").map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>
    <Field label={tr("mt.effective_from")}><input className="ui-input" type="date" value={f.effective_from} onChange={set("effective_from")}/></Field>
  </FormRow>
    <Field label={tr("mt.body")}><textarea className="ui-input" rows={2} value={f.body} onChange={set("body")} data-testid="dc-f-body"/></Field>
    <FormRow>
      <Field label={tr("mt.by_matrix")}><select className="ui-input" value={f.action_type} onChange={set("action_type")}><option value="">—</option>
        {meta.action_types.map((a: string) => <option key={a} value={a}>{lbl("mt.at_", a)}</option>)}</select></Field>
      <Field label={tr("mt.basis")}><input className="ui-input" value={f.authority_basis} placeholder={tr("mt.basis_ph")} onChange={set("authority_basis")} data-testid="dc-f-basis"/></Field>
    </FormRow>
    <label className="biz-check"><input type="checkbox" checked={f.agent_visible} onChange={set("agent_visible")}/> {tr("mt.agent_visible")}</label>
    <div className="tmRow"><button className="ui-btn is-primary" disabled={!f.title.trim()} data-testid="dc-f-save" onClick={async () => { setError(null); try {
      await apiMeetings.decision({company_id: companyId, meeting_id: meetingId || null, ...f, action_type: f.action_type || null,
        decided_by_member_id: f.decided_by_member_id ? Number(f.decided_by_member_id) : null, effective_from: f.effective_from || null});
      toast(tr("mt.decision_saved")); onDone(); } catch (e) { setError(e); } }}>{tr("mt.record")}</button></div>
  </section>;
}

function MeetingDetail({id, can, meta, onChanged, onClose}: {id: number; can: boolean; meta: any; onChanged: () => void; onClose: () => void}) {
  const {data, error, reload, setError} = useLoad(() => apiMeetings.get(id), [id]);
  const [busy, setBusy] = useState(false), [notes, setNotes] = useState<string | null>(null), [note, setNote] = useState("");
  const [act, setAct] = useState({title: "", assignee_member_id: "", due_date: ""}), [dec, setDec] = useState(false);
  const toast = useToast();
  if (error && !data) return <ErrorBanner error={bizErr(error)} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={3} h={40}/>;
  const m: any = data;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); await reload(); onChanged(); } catch (e) { setError(bizErr(e)); } finally { setBusy(false); }
  }
  const draft = m.status === "draft";
  return <section className="ui-panel tm-card" data-testid="mt-detail">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <div className="tmRow"><h3>{m.title}</h3><span className="ui-grow"/><button className="ui-btn is-ghost is-sm" onClick={onClose}>{tr("docs.close")}</button></div>
    <div className="tmRow biz-wrap">
      <StatusPill tone={MS_TONE[m.status]}>{lbl("mt.ms_", m.status)}</StatusPill>
      <span className="ui-pill">{lbl("mt.k_", m.kind)} · {fmtDateTime(m.held_at)}</span>
      {m.chair && <span className="ui-pill">{tr("mt.chair")}: <b>{m.chair}</b></span>}
      {m.approver && <span className="ui-pill">{tr("mt.approver")}: <b>{m.approver}</b></span>}
      {m.minutes_document && <span className="ui-pill is-ok">{tr("mt.stored_as")}: <code className="doc-code">{m.minutes_document.doc_code}</code></span>}
      {m.rhythm_report && <span className="ui-pill">{tr("mt.linked_report")}: {lbl("mt.rk_", m.rhythm_report.kind)} {m.rhythm_report.period_key}</span>}
    </div>
    <p><small>{tr("mt.attendees")}: {m.attendees.map((a: any) => a.name).join(", ") || "—"}</small></p>
    {m.agenda && <p className="tmGuide" style={{whiteSpace: "pre-wrap"}}>{m.agenda}</p>}
    <h4 className="ops-cat">{tr("mt.notes")}</h4>
    {can && draft ? <><textarea className="ui-input" rows={4} value={notes ?? m.notes} onChange={e => setNotes(e.target.value)} data-testid="mt-notes"/>
      <div className="tmRow biz-wrap"><button className="ui-btn is-ghost is-sm" disabled={busy || notes === null} onClick={() => run(() => apiMeetings.patch(m.id, {notes}), tr("docs.saved"))}>{tr("mt.save_notes")}</button>
        <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(async () => { if (notes !== null) await apiMeetings.patch(m.id, {notes}); return apiMeetings.draft(m.id); }, tr("mt.drafted"))} data-testid="mt-draft">{tr("mt.draft_minutes")}</button></div></>
      : <p style={{whiteSpace: "pre-wrap"}}><small>{m.notes || "—"}</small></p>}
    <h4 className="ops-cat">{tr("mt.minutes")}</h4>
    {m.minutes ? <pre className="biz-minutes" data-testid="mt-minutes">{m.minutes}</pre> : <p><small>{tr("mt.no_minutes")}</small></p>}
    {m.locked && <p><small>{tr("mt.locked_hint")}</small></p>}
    {can && draft && m.minutes && <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => run(() => apiMeetings.submit(m.id), tr("mt.submitted"))} data-testid="mt-submit">{tr("mt.submit")}</button>}
    {m.status === "in_review" && <div className="tmRow biz-wrap">
      <input className="ui-input" placeholder={tr("cat.decide_note")} value={note} onChange={e => setNote(e.target.value)}/>
      <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => run(() => apiMeetings.decide(m.id, "approved", note), tr("mt.approved"))} data-testid="mt-approve">{tr("mt.approve")}</button>
      <button className="ui-btn is-ghost is-sm" disabled={busy || note.trim().length < 3} onClick={() => run(() => apiMeetings.decide(m.id, "rejected", note), tr("mt.returned"))}>{tr("mt.return")}</button></div>}
    <h4 className="ops-cat">{tr("mt.actions")}</h4>
    <ul className="biz-timeline" data-testid="mt-actions">{m.actions.length === 0 ? <li><small>{tr("mt.no_actions")}</small></li> : m.actions.map((a: any) => <li key={a.id}>
      <b>{a.title}</b> — {a.assignee || "—"}{a.due_date ? ` · ${fmtDate(a.due_date)}` : ""} · <a href={`/app/tasks/${a.task_id}`}>#{a.task_id}</a>{" "}
      <StatusPill tone={a.task_status === "done" ? "ok" : "wait"}>{a.task_status ? lbl("mt.ts_", a.task_status) : "—"}</StatusPill></li>)}</ul>
    {can && <FormRow>
      <Field label={tr("mt.action")}><input className="ui-input" value={act.title} onChange={e => setAct({...act, title: e.target.value})} data-testid="mt-a-title"/></Field>
      <Field label={tr("mt.assignee")}><select className="ui-input" value={act.assignee_member_id} onChange={e => setAct({...act, assignee_member_id: e.target.value})} data-testid="mt-a-who"><option value="">—</option>
        {meta.members.map((x: any) => <option key={x.id} value={x.id}>{x.name}{x.type === "agent" ? " (agent)" : ""}</option>)}</select></Field>
      <Field label={tr("mt.due")}><input className="ui-input" type="date" value={act.due_date} onChange={e => setAct({...act, due_date: e.target.value})}/></Field>
      <Field label=" "><button className="ui-btn is-ghost" disabled={busy || !act.title.trim() || !act.assignee_member_id} data-testid="mt-a-save"
        onClick={() => run(() => apiMeetings.actions(m.id, [{...act, assignee_member_id: Number(act.assignee_member_id), due_date: act.due_date || null}]), tr("mt.action_created")).then(() => setAct({title: "", assignee_member_id: "", due_date: ""}))}>{tr("mt.to_task")}</button></Field>
    </FormRow>}
    <h4 className="ops-cat">{tr("mt.decisions_here")}</h4>
    <ul className="biz-timeline">{m.decisions.map((x: any) => <li key={x.id}><code className="doc-code">{x.number}</code> <b>{x.title}</b> — {x.body} <StatusPill tone={DS_TONE[x.status] || "neutral"}>{lbl("mt.ds_", x.status)}</StatusPill></li>)}</ul>
    {can && (dec ? <DecisionForm companyId={m.company_id} meta={meta} meetingId={m.id} setError={(e: any) => setError(bizErr(e))} onDone={() => { setDec(false); reload(); onChanged(); }}/>
      : <button className="ui-btn is-ghost is-sm" onClick={() => setDec(true)}>{tr("mt.new_decision")}</button>)}
  </section>;
}

function DecisionPreview({companyId}: {companyId: number}) {
  const [q, setQ] = useState(""), [res, setRes] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  return <div className="ui-panel tm-card" data-testid="dc-preview">
    <h4 className="ops-cat">{tr("crm.preview")}</h4><p className="tmGuide">{tr("mt.preview_hint")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)}/> : null}
    <div className="tmRow biz-wrap"><input className="ui-input" value={q} placeholder={tr("mt.preview_ph")} onChange={e => setQ(e.target.value)}/>
      <button className="ui-btn is-ghost is-sm" onClick={async () => { setErr(null); try { setRes(await apiMeetings.preview(companyId, q)); } catch (e) { setErr(bizErr(e)); } }}>{tr("crm.preview_go")}</button></div>
    {res && <ul className="cat-preview">{res.decisions.length === 0 ? <li><small>{tr("mt.preview_none")}</small></li> : res.decisions.map((x: any) => <li key={x.id}>
      <code className="doc-code">{x.cite}</code> <b>{x.title}</b> — {x.decision}<br/><small>{x.decided_by || "—"} · {x.authority_basis} · {fmtDate(x.effective_from)}</small></li>)}</ul>}
  </div>;
}
