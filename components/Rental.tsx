"use client";
// R1 — vai trò theo công ty (chủ / quản lý / người duyệt / người xem) + một người nhiều ghế.
// R2 — cho thuê agent (seat_leases): bên cho thuê "Cho thuê", bên thuê "Agent đi thuê".
import {useState} from "react";
import {apiAgentsHR, apiCompany, apiLearning, apiRental} from "../lib/api";
import {ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {fmtUsd, t as tr, type Key} from "../lib/i18n";

/** Điều khoản thuê ghép theo ngôn ngữ từ số liệu (USD), không hiện câu tiếng Việt backend ghép sẵn. */
export function termsLine(t: any): string {
  if (!t) return "";
  const parts: string[] = [];
  if (t.price_per_task_usd) parts.push(tr("rental.t_task", {p0: fmtUsd(t.price_per_task_usd)}));
  if (t.price_per_hour_usd) parts.push(tr("rental.t_hour", {p0: fmtUsd(t.price_per_hour_usd)}));
  if (t.price_per_month_usd) parts.push(tr("rental.t_month", {p0: fmtUsd(t.price_per_month_usd)}));
  parts.push(tr("rental.t_markup", {p0: t.markup_pct || 0}));
  if (t.monthly_cost_cap_usd) parts.push(tr("rental.t_cap", {p0: fmtUsd(t.monthly_cost_cap_usd)}));
  return parts.join(" · ");
}
import {useLoad} from "./CompanyOperations";

export const usd = (v: number | null | undefined) => v == null ? "—" : `$${(Math.round(v * 10000) / 10000).toLocaleString("en-US")}`;

export function CompanyRolesTab({companyId, members}: {companyId: number | null; members: any[]}) {
  const {data, error, reload} = useLoad(() => companyId ? apiRental.companyAccess(companyId) : Promise.resolve(null), [companyId]);
  const [email, setEmail] = useState(""), [role, setRole] = useState("viewer"), [seat, setSeat] = useState<string>("");
  const [err, setErr] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  if (!companyId) return <p><small>{tr("rental.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="roles-error"/>;
  if (!data) return <SkeletonRows n={3} h={40}/>;
  const d: any = data;
  const humans = (members || []).filter((m: any) => m.type !== "agent");
  async function save() {
    setBusy(true); setErr(null);
    try {
      const r = await apiRental.setCompanyAccess({company_id: companyId, role, email});
      if (seat) await apiRental.linkSeat({user_id: r.user_id, member_id: Number(seat)});
      toast(tr("rental.role_saved")); setEmail(""); setSeat(""); reload();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function remove(id: number) {
    setBusy(true); setErr(null);
    try { await apiRental.removeCompanyAccess(id); toast(tr("rental.role_removed")); reload(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return <section className="ui-section" data-testid="company-roles">
    <p className="tmGuide">{tr("rental.roles_explain")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} testId="roles-save-error"/> : null}
    <div className="ui-panel"><table className="ui-table" data-testid="company-roles-table"><thead><tr>
      <th>{tr("rental.person")}</th><th>{tr("rental.role")}</th><th>{tr("rental.seat")}</th><th>{tr("rental.status")}</th><th/></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={5}><small>{tr("rental.no_roles")}</small></td></tr>
        : d.items.map((a: any) => <tr key={a.id}><td><b>{a.display_name || a.email}</b><br/><small>{a.email}</small></td>
          <td><span className="ui-pill">{tr(`rental.role_${a.role}` as Key)}</span></td>
          <td>{a.seat ? a.seat.name : "—"}</td><td>{a.status === "active" ? tr("rental.active") : tr("rental.revoked")}</td>
          <td>{a.status === "active" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => remove(a.id)}>{tr("rental.remove")}</button>}</td>
        </tr>)}</tbody></table></div>
    <h3 className="ops-cat">{tr("rental.add_role")}</h3>
    <FormRow>
      <Field label={tr("rental.email")}><input className="ui-input" value={email} onChange={e => setEmail(e.target.value)} data-testid="role-email"/></Field>
      <Field label={tr("rental.role")}><select className="ui-input" value={role} onChange={e => setRole(e.target.value)} data-testid="role-pick">
        {(d.roles || []).map((r: string) => <option key={r} value={r}>{tr(`rental.role_${r}` as Key)}</option>)}</select></Field>
      <Field label={tr("rental.seat_optional")}><select className="ui-input" value={seat} onChange={e => setSeat(e.target.value)}>
        <option value="">—</option>{humans.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>
    </FormRow>
    <button className="ui-btn is-primary" disabled={busy || !email} onClick={save} data-testid="role-save">{tr("rental.save_role")}</button>
  </section>;
}

// ------------------------------------------------------------------ R2 cho thuê agent

const LEASE_PILL: Record<string, string> = {draft: "is-info", active: "is-ok", suspended: "is-wait", ended: "is-outline"};
const dt = (v: string | null | undefined) => v ? new Date(v.endsWith("Z") ? v : v + "Z").toLocaleDateString() : "—";
const num = (v: string) => v.trim() === "" ? undefined : Number(v);

function LeaseStatus({s}: {s: string}) {
  return <span className={`ui-pill ${LEASE_PILL[s] || ""}`}>{tr(`rental.ls_${s}` as Key)}</span>;
}

function Totals({t}: {t: any}) {
  return <div className="org-stats" data-testid="lease-totals">
    <span><b>{t.leases}</b> {tr("rental.leases_n")}</span>
    <span><b>{t.active}</b> {tr("rental.active_n")}</span>
    <span><b>{usd(t.month_billed_usd)}</b> {tr("rental.this_month")}</span>
    <span><b>{usd(t.billed_usd)}</b> {tr("rental.billed_total")}</span>
  </div>;
}

function CostBar({used, cap}: {used: number; cap: number | null}) {
  if (!cap) return <small>{usd(used)} · {tr("rental.no_cap")}</small>;
  const pct = Math.min(100, Math.round((used / cap) * 100));
  return <div title={`${pct}%`}><small>{usd(used)} / {usd(cap)}</small>
    <div className="cst-meter"><i className={pct >= 100 ? "is-hard" : pct >= 80 ? "is-warn" : ""} style={{width: `${pct}%`}}/></div></div>;
}

function ChangeRequests({ls, side, busy, act}: {ls: any; side: string; busy: boolean; act: (f: () => Promise<any>, ok: string) => void}) {
  const items = ls.change_requests || [];
  if (!items.length) return null;
  return <ul className="ops-steps" data-testid={`lease-crs-${ls.id}`}>{items.map((c: any) => <li key={c.id}>
    <small>#{c.id} {Object.entries(c.changes).map(([k, v]) => `${tr(`rental.f_${k}` as Key)}: ${Array.isArray(v) ? v.join(", ") : v ?? "—"}`).join(" · ")}
      {c.note ? ` — ${c.note}` : ""}</small>
    <span className={`ui-pill ${c.status === "approved" ? "is-ok" : c.status === "rejected" ? "is-risk" : "is-wait"}`}>{tr(`rental.cr_${c.status}` as Key)}</span>
    {side === "provider" && c.status === "pending" && <>
      <button className="ui-btn is-sm is-primary" disabled={busy} onClick={() => act(() => apiRental.decideChange(ls.id, c.id, "approved"), tr("rental.cr_done"))} data-testid={`cr-approve-${ls.id}-${c.id}`}>{tr("rental.approve")}</button>
      <button className="ui-btn is-sm is-ghost" disabled={busy} onClick={() => act(() => apiRental.decideChange(ls.id, c.id, "rejected"), tr("rental.cr_done"))}>{tr("rental.reject")}</button></>}
  </li>)}</ul>;
}

function useAct(reload: () => void) {
  const [err, setErr] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  async function act(fn: () => Promise<any>, ok: string) {
    setBusy(true); setErr(null);
    try { const r = await fn(); toast(ok); reload(); return r; } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return {err, setErr, busy, act};
}

const EMPTY_OFFER = {agent: "", markup: "20", task: "", hour: "", month: "", cap: "", ends: "", tools: "", data: "", docs: [] as number[]};

/** Bên cho thuê: chào thuê từ một ghế agent, theo dõi hợp đồng, doanh thu USD, duyệt yêu cầu đổi. */
export function LeaseOutTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload} = useLoad(() => companyId ? apiRental.leases("provider", companyId) : Promise.resolve(null), [companyId]);
  const roster = useLoad(() => companyId ? apiAgentsHR.roster(companyId) : Promise.resolve(null), [companyId]);
  const docs = useLoad(() => apiLearning.docs(), []);
  const {err, setErr, busy, act} = useAct(reload);
  const [f, setF] = useState<typeof EMPTY_OFFER | null>(null);
  const can = !!caps?.manage_roles, canAsk = !!caps?.invite;   // admin: chào/nhận/kết thúc; manager: xin đổi
  if (!companyId) return <p><small>{tr("rental.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="leaseout-error"/>;
  if (!data) return <SkeletonRows n={3} h={44}/>;
  const d: any = data;
  const agents = ((roster.data as any)?.items || []).filter((a: any) => a.lifecycle !== "retired");
  const docItems = ((docs.data as any)?.items || []).filter((x: any) => !x.company_id || x.company_id === companyId);
  async function create() {
    if (!f) return;
    const body: any = {provider_agent_id: Number(f.agent), markup_pct: num(f.markup) ?? 0, price_per_task_usd: num(f.task),
      price_per_hour_usd: num(f.hour), price_per_month_usd: num(f.month), monthly_cost_cap_usd: num(f.cap) ?? null,
      data_handling: f.data, knowledge_doc_ids: f.docs,
      allowed_tools: f.tools.split(",").map(s => s.trim()).filter(Boolean)};
    if (f.ends) body.ends_at = new Date(f.ends + "T23:59:00").toISOString();
    const r = await act(() => apiRental.createOffer(body), tr("rental.offer_created"));
    if (r) setF(null);
  }
  return <section className="ui-section" data-testid="lease-out">
    <p className="tmGuide">{tr("rental.out_explain")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} testId="leaseout-save-error"/> : null}
    <div className="ui-toolbar"><Totals t={d.totals}/>
      <span className="org-stats"><span><b>{usd(d.totals.margin_usd)}</b> {tr("rental.margin")}</span></span>
      <span className="ui-grow"/>
      {can && !f && <button className="ui-btn is-primary" onClick={() => setF({...EMPTY_OFFER})} data-testid="offer-new">{tr("rental.offer_new")}</button>}</div>
    {f && <div className="ui-panel" data-testid="offer-form">
      <FormRow>
        <Field label={tr("rental.agent")}><select className="ui-input" value={f.agent} onChange={e => setF({...f, agent: e.target.value})} data-testid="offer-agent">
          <option value="">—</option>{agents.map((a: any) => <option key={a.agent_id} value={a.agent_id}>{a.name}{a.role ? ` · ${a.role}` : ""}</option>)}</select></Field>
        <Field label={tr("rental.markup")}><input className="ui-input" inputMode="decimal" value={f.markup} onChange={e => setF({...f, markup: e.target.value})} data-testid="offer-markup"/></Field>
        <Field label={tr("rental.cap")}><input className="ui-input" inputMode="decimal" value={f.cap} onChange={e => setF({...f, cap: e.target.value})} data-testid="offer-cap"/></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("rental.per_task")}><input className="ui-input" inputMode="decimal" value={f.task} onChange={e => setF({...f, task: e.target.value})}/></Field>
        <Field label={tr("rental.per_hour")}><input className="ui-input" inputMode="decimal" value={f.hour} onChange={e => setF({...f, hour: e.target.value})}/></Field>
        <Field label={tr("rental.per_month")}><input className="ui-input" inputMode="decimal" value={f.month} onChange={e => setF({...f, month: e.target.value})}/></Field>
        <Field label={tr("rental.ends")}><input className="ui-input" type="date" value={f.ends} onChange={e => setF({...f, ends: e.target.value})}/></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("rental.tools")} hint={tr("rental.tools_hint")}><input className="ui-input" value={f.tools} onChange={e => setF({...f, tools: e.target.value})}/></Field>
        <Field label={tr("rental.data_handling")}><input className="ui-input" value={f.data} onChange={e => setF({...f, data: e.target.value})}/></Field>
      </FormRow>
      {docItems.length > 0 && <Field label={tr("rental.scope_docs")}><div className="tmChecks">{docItems.slice(0, 30).map((x: any) =>
        <label key={x.id} className="tmInline"><input type="checkbox" checked={f.docs.includes(x.id)}
          onChange={e => setF({...f, docs: e.target.checked ? [...f.docs, x.id] : f.docs.filter(i => i !== x.id)})}/> {x.title}</label>)}</div></Field>}
      <p><small>{tr("rental.defaults_line")}</small></p>
      <button className="ui-btn is-primary" disabled={busy || !f.agent} onClick={create} data-testid="offer-save">{tr("rental.offer_create")}</button>{" "}
      <button className="ui-btn is-ghost" onClick={() => setF(null)}>{tr("rental.cancel")}</button>
    </div>}
    <div className="ui-panel"><table className="ui-table" data-testid="lease-out-table"><thead><tr>
      <th>{tr("rental.agent")}</th><th>{tr("rental.renter")}</th><th>{tr("rental.status")}</th><th>{tr("rental.terms")}</th>
      <th>{tr("rental.usage")}</th><th>{tr("rental.revenue")}</th><th/></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={7}><small>{tr("rental.no_offers")}</small></td></tr>
        : d.items.map((ls: any) => <tr key={ls.id} data-testid={`lease-row-${ls.id}`}>
          <td><b>{ls.provider.agent_name}</b><br/><small>#{ls.id} · {tr("rental.until")} {dt(ls.ends_at)}</small></td>
          <td>{ls.renter.company ? <>{ls.renter.company}<br/><small>{ls.renter.organization}</small></>
            : ls.offer_code ? <><code data-testid={`offer-code-${ls.id}`}>{ls.offer_code}</code><br/><small>{tr("rental.share_code")} · {tr("rental.expires")} {dt(ls.offer_expires_at)}</small></> : "—"}</td>
          <td><LeaseStatus s={ls.status}/>{ls.status_reason ? <><br/><small>{ls.status_reason}</small></> : null}</td>
          <td><small>{termsLine(ls.terms)}</small></td>
          <td><CostBar used={ls.usage.month.billed_usd} cap={ls.terms.monthly_cost_cap_usd}/>
            <small>{ls.usage.task_runs} {tr("rental.runs")} · {Object.entries(ls.usage.by_channel || {}).map(([k, v]: any) => `${k} ${v.calls}`).join(" · ")}</small>
            <ChangeRequests ls={ls} side="provider" busy={busy} act={act}/></td>
          <td><b>{usd(ls.usage.billed_usd)}</b><br/><small>{tr("rental.cost")} {usd(ls.usage.cost_usd)} · {tr("rental.margin")} {usd(ls.usage.margin_usd)}</small></td>
          <td className="ui-nowrap">{can && ls.status === "active" && <button className="ui-btn is-sm is-ghost" disabled={busy} onClick={() => act(() => apiRental.leaseStatus(ls.id, "suspend"), tr("rental.suspended_ok"))}>{tr("rental.suspend")}</button>}
            {can && ls.status === "suspended" && <button className="ui-btn is-sm" disabled={busy} onClick={() => act(() => apiRental.leaseStatus(ls.id, "resume"), tr("rental.resumed_ok"))}>{tr("rental.resume")}</button>}
            {can && ls.status !== "ended" && <button className="ui-btn is-sm is-ghost" disabled={busy} onClick={() => { if (confirm(tr("rental.end_confirm"))) act(() => apiRental.endLease(ls.id), tr("rental.ended_ok")); }}>{tr("rental.end")}</button>}</td>
        </tr>)}</tbody></table></div>
  </section>;
}

/** Bên thuê: nhập mã chào thuê, xem ghế đi thuê, chi phí so với trần, xin đổi. */
export function LeasedTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload} = useLoad(() => companyId ? apiRental.leases("renter", companyId) : Promise.resolve(null), [companyId]);
  const positions = useLoad(() => companyId ? apiCompany.positions(companyId) : Promise.resolve(null), [companyId]);
  const {err, setErr, busy, act} = useAct(reload);
  const [code, setCode] = useState(""), [pv, setPv] = useState<any>(null), [pos, setPos] = useState("");
  const [cr, setCr] = useState<{id: number; cap: string; tools: string; note: string} | null>(null);
  const can = !!caps?.manage_roles, canAsk = !!caps?.invite;   // admin: chào/nhận/kết thúc; manager: xin đổi
  if (!companyId) return <p><small>{tr("rental.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="leased-error"/>;
  if (!data) return <SkeletonRows n={3} h={44}/>;
  const d: any = data;
  const posItems = ((positions.data as any)?.items || []);
  async function preview() {
    setErr(null); setPv(null);
    try { setPv(await apiRental.previewOffer(code.trim())); } catch (e) { setErr(e); }
  }
  async function accept() {
    const r = await act(() => apiRental.acceptOffer({offer_code: code.trim(), company_id: companyId, position_id: Number(pos)}), tr("rental.accepted_ok"));
    if (r) { setCode(""); setPv(null); setPos(""); }
  }
  async function sendCr() {
    if (!cr) return;
    const changes: any = {};
    if (cr.cap.trim()) changes.monthly_cost_cap_usd = Number(cr.cap);
    if (cr.tools.trim()) changes.allowed_tools = cr.tools.split(",").map(s => s.trim()).filter(Boolean);
    const r = await act(() => apiRental.requestChange(cr.id, {changes, note: cr.note}), tr("rental.cr_sent"));
    if (r) setCr(null);
  }
  return <section className="ui-section" data-testid="leased">
    <p className="tmGuide">{tr("rental.in_explain")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} testId="leased-save-error"/> : null}
    <div className="ui-toolbar"><Totals t={d.totals}/></div>
    {can && <div className="ui-panel" data-testid="accept-form">
      <h3 className="ops-cat">{tr("rental.accept_title")}</h3>
      <FormRow>
        <Field label={tr("rental.offer_code")}><input className="ui-input" value={code} onChange={e => { setCode(e.target.value); setPv(null); }} data-testid="accept-code"/></Field>
        <Field label={tr("rental.position")}><select className="ui-input" value={pos} onChange={e => setPos(e.target.value)} data-testid="accept-position">
          <option value="">—</option>{posItems.map((p: any) => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
      </FormRow>
      {pv && <p data-testid="accept-preview"><b>{pv.agent_name}</b> · {pv.provider_company}<br/><small>{pv.terms_detail ? termsLine(pv.terms_detail) : pv.terms}</small>
        {pv.allowed_tools?.length ? <><br/><small>{tr("rental.tools")}: {pv.allowed_tools.join(", ")}</small></> : null}</p>}
      <button className="ui-btn" disabled={busy || !code.trim()} onClick={preview} data-testid="accept-preview-btn">{tr("rental.preview")}</button>{" "}
      <button className="ui-btn is-primary" disabled={busy || !pv || !pos} onClick={accept} data-testid="accept-save">{tr("rental.accept")}</button>
    </div>}
    <div className="ui-panel"><table className="ui-table" data-testid="leased-table"><thead><tr>
      <th>{tr("rental.agent")}</th><th>{tr("rental.provider")}</th><th>{tr("rental.status")}</th><th>{tr("rental.terms")}</th>
      <th>{tr("rental.cost_vs_cap")}</th><th/></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={6}><small>{tr("rental.no_leased")}</small></td></tr>
        : d.items.map((ls: any) => <tr key={ls.id} data-testid={`leased-row-${ls.id}`}>
          <td><b>{ls.provider.agent_name}</b><br/><small>#{ls.id} · {tr("rental.until")} {dt(ls.ends_at)}</small></td>
          <td>{ls.provider.company}<br/><small>{ls.provider.organization}</small></td>
          <td><LeaseStatus s={ls.status}/>{ls.block_reason ? <><br/><small>{ls.block_reason}</small></> : null}</td>
          <td><small>{termsLine(ls.terms)}</small><br/><small>{tr("rental.approvals_line")}</small></td>
          <td><CostBar used={ls.usage.month.billed_usd} cap={ls.terms.monthly_cost_cap_usd}/>
            <small>{tr("rental.billed_total")} {usd(ls.usage.billed_usd)} · {ls.usage.task_runs} {tr("rental.runs")}</small>
            <ChangeRequests ls={ls} side="renter" busy={busy} act={act}/>
            {cr?.id === ls.id && <div className="ui-panel" data-testid={`cr-form-${ls.id}`}>
              <FormRow>
                <Field label={tr("rental.cap")}><input className="ui-input" inputMode="decimal" value={cr.cap} onChange={e => setCr({...cr, cap: e.target.value})} data-testid="cr-cap"/></Field>
                <Field label={tr("rental.tools")}><input className="ui-input" value={cr.tools} onChange={e => setCr({...cr, tools: e.target.value})}/></Field>
              </FormRow>
              <Field label={tr("rental.note")}><input className="ui-input" value={cr.note} onChange={e => setCr({...cr, note: e.target.value})}/></Field>
              <button className="ui-btn is-primary is-sm" disabled={busy || (!cr.cap.trim() && !cr.tools.trim())} onClick={sendCr} data-testid="cr-send">{tr("rental.cr_send")}</button>{" "}
              <button className="ui-btn is-ghost is-sm" onClick={() => setCr(null)}>{tr("rental.cancel")}</button></div>}</td>
          <td className="ui-nowrap">{canAsk && ls.status !== "ended" && !cr && <button className="ui-btn is-sm" onClick={() => setCr({id: ls.id, cap: "", tools: "", note: ""})} data-testid={`cr-new-${ls.id}`}>{tr("rental.cr_new")}</button>}
            {can && ls.status !== "ended" && <button className="ui-btn is-sm is-ghost" disabled={busy} onClick={() => { if (confirm(tr("rental.end_confirm"))) act(() => apiRental.endLease(ls.id), tr("rental.ended_ok")); }}>{tr("rental.end")}</button>}</td>
        </tr>)}</tbody></table></div>
  </section>;
}
