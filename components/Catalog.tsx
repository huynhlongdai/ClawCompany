"use client";
// M3f — Công ty › Tài liệu & tri thức › Sản phẩm & giá: danh mục sản phẩm/dịch vụ (SKU, đơn vị, chính sách riêng, tài liệu
// mô tả), giá đang áp dụng + lịch sử giá, đề xuất giá mới đi qua ma trận price_change, xem trước đúng thứ agent nhận từ tool.
import {useState} from "react";
import {apiCatalog, apiDocs} from "../lib/api";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {fmtPrice, getLocale, t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

const day = (s?: string | null) => s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleDateString(getLocale() === "en" ? "en-GB" : "vi-VN") : "—";
const ST_TONE: Record<string, any> = {active: "ok", draft: "neutral", discontinued: "risk"};
const PR_TONE: Record<string, any> = {approved: "ok", pending: "wait", rejected: "risk", cancelled: "neutral"};
const pct = (v: number | null | undefined) => v == null ? tr("cat.new_price") : `${v > 0 ? "+" : ""}${v}%`;

export function CatalogTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [q, setQ] = useState(""), [sel, setSel] = useState<number | null>(null), [adding, setAdding] = useState(false);
  const {data, error, reload, setError} = useLoad(() => companyId ? apiCatalog.list(companyId, {q}) : Promise.resolve(null), [companyId]);
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="catalog-error"/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  return <section className="ui-section" data-testid="catalog">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="catalog-save-error"/> : null}
    <p className="tmGuide">{tr("cat.explain", {p0: d.high_pct})}</p>
    <div className="tmRow" data-testid="catalog-stats">
      <span className="ui-pill">{tr("cat.total")}: <b>{d.counts.total}</b></span>
      <span className="ui-pill is-ok">{tr("cat.priced")}: <b>{d.counts.priced}</b></span>
      <span className={"ui-pill" + (d.counts.pending ? " is-wait" : "")}>{tr("cat.pending")}: <b>{d.counts.pending}</b></span>
      <span className="ui-grow"/>
      {can && <button className="ui-btn is-primary is-sm" onClick={() => { setAdding(!adding); setSel(null); }} data-testid="cat-new">{tr("cat.new")}</button>}
    </div>
    {!!caps?.manage_roles && <ThresholdSetting companyId={companyId} current={d.high_pct} setError={setError} onSaved={reload}/>}
    {adding && <NewProduct companyId={companyId} setError={setError} onDone={(p: any) => { setAdding(false); reload(); setSel(p.id); }} onCancel={() => setAdding(false)}/>}
    <div className="tmRow">
      <input className="ui-input" placeholder={tr("cat.search")} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && reload()} data-testid="cat-q"/>
    </div>
    <div className="ui-panel"><table className="ui-table cat-table" data-testid="cat-table"><thead><tr>
      <th>{tr("cat.sku")}</th><th>{tr("cat.name")}</th><th>{tr("cat.unit")}</th><th>{tr("cat.price_now")}</th><th>{tr("cat.status")}</th></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={5}><EmptyState compact mood="chao" title={tr("cat.empty")}>{tr("cat.empty_hint")}</EmptyState></td></tr>
        : d.items.map((x: any) => <tr key={x.id} className={sel === x.id ? "is-selected" : ""} style={{cursor: "pointer"}} onClick={() => { setSel(x.id); setAdding(false); }} data-testid={`cat-row-${x.sku}`}>
          <td><code className="doc-code">{x.sku}</code></td>
          <td><code className="doc-code cat-sku-m">{x.sku}</code><b>{x.name}</b>{x.kind === "service" && <> <span className="ui-pill is-outline">{tr("cat.service")}</span></>}{x.category && <><br/><small>{x.category}</small></>}</td>
          <td>{x.unit}</td>
          <td className="cat-money">{x.current_price ? <b>{fmtPrice(x.current_price)}</b> : <small>{tr("cat.no_price")}</small>}
            {x.pending_price && <><br/><StatusPill tone="wait">{tr("cat.pending_short", {p0: fmtPrice(x.pending_price), p1: pct(x.pending_price.change_pct)})}</StatusPill></>}
            {x.scheduled_price && <><br/><small>{tr("cat.scheduled", {p0: fmtPrice(x.scheduled_price), p1: day(x.scheduled_price.effective_from)})}</small></>}</td>
          <td><StatusPill tone={ST_TONE[x.status]}>{tr(`cat.st_${x.status}` as Key)}</StatusPill></td>
        </tr>)}</tbody></table></div>
    {sel && <ProductDetail id={sel} can={can} onChanged={reload} onClose={() => setSel(null)}/>}
    <AgentPreview companyId={companyId}/>
  </section>;
}

function NewProduct({companyId, setError, onDone, onCancel}: any) {
  const [f, setF] = useState<any>({sku: "", name: "", kind: "product", unit: "cái", category: "", price: "", currency: "VND", return_days: "", warranty_months: "", description: ""});
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const set = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  async function save() {
    setSaving(true); setError(null);
    try {
      const policies: any = {};
      if (f.return_days !== "") policies.return_days = Number(f.return_days);
      if (f.warranty_months !== "") policies.warranty_months = Number(f.warranty_months);
      const r = await apiCatalog.create({company_id: companyId, sku: f.sku, name: f.name, kind: f.kind, unit: f.unit, category: f.category,
        description: f.description, policies, price: f.price || undefined, currency: f.currency});
      toast(r.price_request && !r.price_request.auto_approved ? tr("cat.created_pending") : tr("cat.created")); onDone(r);
    } catch (e) { setError(e); } finally { setSaving(false); }
  }
  return <section className="ui-panel tm-card" data-testid="cat-form">
    <fieldset className="ui-form" disabled={saving}>
      <FormRow>
        <Field label={tr("cat.sku")}><input className="ui-input" value={f.sku} onChange={set("sku")} placeholder="BAT-MEN-LAM" data-testid="cat-f-sku"/></Field>
        <Field label={tr("cat.name")}><input className="ui-input" value={f.name} onChange={set("name")} data-testid="cat-f-name"/></Field>
        <Field label={tr("cat.kind")}><select className="ui-input" value={f.kind} onChange={set("kind")}>
          <option value="product">{tr("cat.product")}</option><option value="service">{tr("cat.service")}</option></select></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("cat.unit")}><input className="ui-input" value={f.unit} onChange={set("unit")}/></Field>
        <Field label={tr("cat.category")}><input className="ui-input" value={f.category} onChange={set("category")}/></Field>
        <Field label={tr("cat.first_price")}><input className="ui-input" inputMode="numeric" value={f.price} onChange={set("price")} placeholder="185000" data-testid="cat-f-price"/></Field>
        <Field label={tr("cat.currency")}><select className="ui-input" value={f.currency} onChange={set("currency")}><option>VND</option><option>USD</option></select></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("cat.return_days")}><input className="ui-input" inputMode="numeric" value={f.return_days} onChange={set("return_days")}/></Field>
        <Field label={tr("cat.warranty_months")}><input className="ui-input" inputMode="numeric" value={f.warranty_months} onChange={set("warranty_months")}/></Field>
      </FormRow>
      <Field label={tr("cat.description")}><textarea className="ui-input" rows={3} value={f.description} onChange={set("description")}/></Field>
      <p><small>{tr("cat.policy_hint")}</small></p>
      <div className="tmRow">
        <button className="ui-btn is-primary" disabled={!f.sku.trim() || !f.name.trim()} onClick={save} data-testid="cat-f-save">{tr("cat.save")}</button>
        <button className="ui-btn is-ghost" onClick={onCancel}>{tr("docs.cancel")}</button>
      </div>
    </fieldset>
  </section>;
}

function ProductDetail({id, can, onChanged, onClose}: {id: number; can: boolean; onChanged: () => void; onClose: () => void}) {
  const {data, error, reload, setError} = useLoad(() => apiCatalog.get(id), [id]);
  const [pf, setPf] = useState({amount: "", currency: "VND", effective_from: "", note: ""}), [busy, setBusy] = useState(false), [note, setNote] = useState("");
  const docs = useLoad(() => data ? apiDocs.list((data as any).company_id, {status: "published"}) : Promise.resolve(null), [(data as any)?.company_id]);
  const toast = useToast();
  if (error && !data) return <ErrorBanner error={error} onRetry={reload}/>;
  if (!data) return <SkeletonRows n={3} h={40}/>;
  const p: any = data;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(ok); await reload(); onChanged(); return r; } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const pend = p.pending_price;
  return <section className="ui-panel tm-card" data-testid="cat-detail">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="cat-detail-error"/> : null}
    <div className="tmRow"><h3><code className="doc-code">{p.sku}</code> {p.name}</h3><span className="ui-grow"/>
      <button className="ui-btn is-ghost is-sm" onClick={onClose}>{tr("docs.close")}</button></div>
    <p>{p.description}</p>
    <div className="tmRow">
      <span className="ui-pill">{tr("cat.price_now")}: <b>{p.current_price ? `${fmtPrice(p.current_price)} / ${p.unit}` : tr("cat.no_price")}</b></span>
      {p.policies.return_days != null && <span className="ui-pill">{tr("cat.return_days")}: <b>{p.policies.return_days}</b></span>}
      {p.policies.warranty_months != null && <span className="ui-pill">{tr("cat.warranty_months")}: <b>{p.policies.warranty_months}</b></span>}
      <span className="ui-pill">{tr("cat.sheet")}: <b>{p.document ? `${p.document.doc_code} v${p.document.version_no}` : "—"}</b></span>
      <StatusPill tone={ST_TONE[p.status]}>{tr(`cat.st_${p.status}` as Key)}</StatusPill>
    </div>
    {can && <div className="tmRow">
      <select className="ui-input" value={p.document?.id || ""} onChange={e => run(() => apiCatalog.patch(p.id, {document_id: e.target.value ? Number(e.target.value) : null}), tr("docs.saved"))} data-testid="cat-sheet-pick">
        <option value="">{tr("cat.sheet_pick")}</option>
        {((docs.data as any)?.items || []).map((x: any) => <option key={x.id} value={x.id}>{x.doc_code} · {x.title}</option>)}</select>
      {p.status !== "discontinued"
        ? <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiCatalog.patch(p.id, {status: "discontinued"}), tr("docs.saved"))}>{tr("cat.discontinue")}</button>
        : <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiCatalog.patch(p.id, {status: "active"}), tr("docs.saved"))}>{tr("cat.reactivate")}</button>}
    </div>}
    {pend && <div className="ui-banner" data-testid="cat-pending">
      <div><b>{tr("cat.pending_title", {p0: fmtPrice(pend), p1: pct(pend.change_pct)})}</b><br/>
        <small>{tr("cat.pending_detail", {p0: day(pend.effective_from), p1: tr(pend.risk === "high" ? "cat.risk_high" : "cat.risk_normal")})}{pend.note ? ` · ${pend.note}` : ""}</small>
        <div className="tmRow">
          <input className="ui-input" placeholder={tr("cat.decide_note")} value={note} onChange={e => setNote(e.target.value)}/>
          <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => run(() => apiCatalog.decide(pend.id, "approved", note), tr("cat.approved"))} data-testid="cat-approve">{tr("cat.approve")}</button>
          <button className="ui-btn is-ghost is-sm" disabled={busy || !note.trim()} onClick={() => run(() => apiCatalog.decide(pend.id, "rejected", note), tr("cat.rejected"))}>{tr("cat.reject")}</button>
          {can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiCatalog.cancel(pend.id), tr("docs.saved"))}>{tr("cat.cancel_req")}</button>}
        </div></div></div>}
    {can && !pend && <><h4 className="ops-cat">{tr("cat.propose")}</h4>
      <FormRow>
        <Field label={tr("cat.new_amount")}><input className="ui-input" inputMode="numeric" value={pf.amount} onChange={e => setPf({...pf, amount: e.target.value})} data-testid="cat-p-amount"/></Field>
        <Field label={tr("cat.currency")}><select className="ui-input" value={pf.currency} onChange={e => setPf({...pf, currency: e.target.value})}><option>VND</option><option>USD</option></select></Field>
        <Field label={tr("cat.effective_from")}><input className="ui-input" type="date" value={pf.effective_from} onChange={e => setPf({...pf, effective_from: e.target.value})}/></Field>
        <Field label={tr("cat.reason")}><input className="ui-input" value={pf.note} onChange={e => setPf({...pf, note: e.target.value})}/></Field>
      </FormRow>
      <button className="ui-btn is-primary" disabled={busy || !pf.amount} data-testid="cat-p-save"
        onClick={() => run(() => apiCatalog.propose(p.id, {...pf, effective_from: pf.effective_from || undefined}), tr("cat.proposed")).then(() => setPf({amount: "", currency: "VND", effective_from: "", note: ""}))}>{tr("cat.propose_btn")}</button></>}
    <h4 className="ops-cat">{tr("cat.history")}</h4>
    <div className="ui-panel"><table className="ui-table" data-testid="cat-history"><thead><tr>
      <th>{tr("cat.price")}</th><th>{tr("cat.change")}</th><th>{tr("cat.window")}</th><th>{tr("cat.status")}</th><th>{tr("cat.who")}</th></tr></thead>
      <tbody>{p.history.map((h: any) => <tr key={h.id} className={h.in_effect ? "is-selected" : ""}>
        <td className="cat-money"><b>{fmtPrice(h)}</b>{h.channel !== "default" && <><br/><small>{h.channel}</small></>}</td>
        <td>{pct(h.change_pct)}</td>
        <td>{day(h.effective_from)} → {h.effective_to ? day(h.effective_to) : "…"}</td>
        <td><StatusPill tone={PR_TONE[h.status]}>{tr(`cat.ps_${h.status}` as Key)}</StatusPill>
          {h.in_effect && <> <StatusPill tone="ok">{tr("cat.in_effect")}</StatusPill></>}{h.expired && <> <StatusPill tone="neutral">{tr("cat.expired")}</StatusPill></>}</td>
        <td><small>{[h.requested_by && `${tr("cat.by")} ${h.requested_by}`, h.decided_by && `${tr("cat.decided_by")} ${h.decided_by}`].filter(Boolean).join(" · ") || "—"}</small></td>
      </tr>)}</tbody></table></div>
  </section>;
}

function AgentPreview({companyId}: {companyId: number}) {
  const [q, setQ] = useState(""), [res, setRes] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  async function go() { setErr(null); try { setRes(await apiCatalog.lookup(companyId, q)); } catch (e) { setErr(e); } }
  return <div className="ui-panel tm-card" data-testid="cat-preview">
    <h4 className="ops-cat">{tr("cat.preview")}</h4>
    <p className="tmGuide">{tr("cat.preview_hint")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)}/> : null}
    <div className="tmRow">
      <input className="ui-input" value={q} placeholder={tr("cat.preview_ph")} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && go()} data-testid="cat-preview-q"/>
      <button className="ui-btn is-ghost is-sm" disabled={!q.trim()} onClick={go} data-testid="cat-preview-go">{tr("cat.preview_go")}</button>
    </div>
    {res && (res.products.length === 0 ? <p><small>{res.note}</small></p> : <ul className="cat-preview" data-testid="cat-preview-out">
      {res.products.map((x: any) => <li key={x.sku}><code className="doc-code">{x.sku}</code> <b>{x.name}</b> — {x.price ? <b>{fmtPrice(x.price)} / {x.price.per}</b> : <StatusPill tone="risk">{tr("cat.no_price")}</StatusPill>}
        {x.warning && <><br/><small>{x.warning}</small></>}
        {Object.keys(x.policies || {}).length > 0 && <><br/><small>{Object.entries(x.policies).map(([k, v]: any) => `${k}: ${typeof v === "object" ? `${v.value} (${v.source})` : v}`).join(" · ")}</small></>}</li>)}
    </ul>)}
  </div>;
}

/** Ngưỡng % đổi giá cần chủ duyệt — cài đặt theo công ty (chỉ quản trị công ty). Không hồi tố đề xuất đang chờ. */
function ThresholdSetting({companyId, current, setError, onSaved}: {companyId: number; current: number; setError: (e: any) => void; onSaved: () => void}) {
  const [open, setOpen] = useState(false), [v, setV] = useState(String(current)), [busy, setBusy] = useState(false);
  const toast = useToast();
  async function save(val: number | null) {
    setBusy(true); setError(null);
    try { const r = await apiCatalog.saveSettings({company_id: companyId, high_pct: val}); toast(tr("cat.thr_saved", {p0: r.high_pct})); setOpen(false); onSaved(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  if (!open) return <p data-testid="cat-threshold"><small>{tr("cat.thr_line", {p0: current})}</small>{" "}
    <button className="ui-btn is-ghost is-sm" onClick={() => { setV(String(current)); setOpen(true); }} data-testid="cat-threshold-edit">{tr("cat.thr_edit")}</button></p>;
  return <div className="ui-panel tmRow" data-testid="cat-threshold-form" style={{flexWrap: "wrap", gap: 8, padding: "10px 12px"}}>
    <label><small>{tr("cat.thr_label")}</small>{" "}
      <input className="ui-input" type="number" min={1} max={100} value={v} onChange={e => setV(e.target.value)} style={{width: 90}} data-testid="cat-threshold-input"/> %</label>
    <button className="ui-btn is-primary is-sm" disabled={busy || !v} onClick={() => save(Number(v))} data-testid="cat-threshold-save">{tr("cat.thr_save")}</button>
    <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => save(null)}>{tr("cat.thr_default")}</button>
    <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => setOpen(false)}>{tr("cat.cancel_edit")}</button>
    <small style={{flexBasis: "100%"}}>{tr("cat.thr_hint")}</small>
  </div>;
}
