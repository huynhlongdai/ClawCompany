"use client";
// M3a — Công ty › Tài liệu & tri thức › Thư viện: cây 8 ngăn theo loại, lọc, trang tài liệu (siêu dữ liệu, nội dung
// bản đang hiệu lực, phiên bản đang soạn / chờ duyệt, lịch sử phiên bản + so sánh), duyệt theo ma trận, tải tệp gốc.
import {useEffect, useState} from "react";
import {apiCompany, apiDocs} from "../lib/api";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill, toneOf} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {getLocale, t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

const lbl = (x: any) => x ? (getLocale() === "en" ? x.en : x.vi) : "";
const day = (s?: string | null) => s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleDateString(getLocale() === "en" ? "en-GB" : "vi-VN") : "—";
const REVIEW_TONE: Record<string, any> = {ok: "ok", due: "wait", stale: "risk", none: "neutral"};

export function DocLibraryTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [group, setGroup] = useState(""), [status, setStatus] = useState(""), [q, setQ] = useState(""), [review, setReview] = useState("");
  const {data, error, reload, setError} = useLoad(() => companyId ? apiDocs.list(companyId, {group, status, q, review}) : Promise.resolve(null),
    [companyId, group, status, review]);
  const [sel, setSel] = useState<number | null>(() => {   // M3e: ?doc=<id> (từ bảng vòng học) mở thẳng tài liệu
    if (typeof window === "undefined") return null;
    const v = Number(new URLSearchParams(window.location.search).get("doc")); return v > 0 ? v : null; }), [mode, setMode] = useState<"" | "new" | "upload">("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="docs-error"/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  const tax = d.taxonomy, types: any[] = tax.types;
  const typeOf = (k: string) => types.find(x => x.key === k);
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(ok); await reload(); return r; } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <section className="ui-section" data-testid="doc-library">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="docs-save-error"/> : null}
    <p className="tmGuide">{tr("docs.explain")}</p>
    <div className="tmRow" data-testid="doc-stats">
      <span className="ui-pill">{tr("docs.total")}: <b>{d.counts.total}</b></span>
      <span className="ui-pill is-ok">{tr("docs.published")}: <b>{d.counts.published}</b></span>
      <span className="ui-pill is-wait">{tr("docs.in_progress")}: <b>{d.counts.draft_or_review}</b></span>
      <button className={"ui-pill" + (d.counts.review_due ? " is-risk" : "")} onClick={() => setReview(review ? "" : "due,stale")} data-testid="doc-review-filter">
        {tr("docs.review_due")}: <b>{d.counts.review_due}</b></button>
      <span className="ui-grow"/>
      {can && <button className="ui-btn is-primary is-sm" onClick={() => { setMode(mode === "new" ? "" : "new"); setSel(null); }} data-testid="doc-new">{tr("docs.new")}</button>}
      {can && <button className="ui-btn is-ghost is-sm" onClick={() => { setMode(mode === "upload" ? "" : "upload"); setSel(null); }} data-testid="doc-upload">{tr("docs.upload")}</button>}
      {can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.importSops(companyId), tr("docs.sops_imported"))} data-testid="doc-import-sops">{tr("docs.import_sops")}</button>}
    </div>
    {mode && <NewDoc mode={mode} companyId={companyId} types={types} groups={tax.groups} busy={busy}
      onCancel={() => setMode("")} onDone={(doc: any) => { setMode(""); reload(); setSel(doc?.id || null); }} setError={setError}/>}
    <div className="doc-layout">
      <nav className="ui-panel doc-tree" data-testid="doc-tree">
        <button className={"doc-tree-item" + (!group ? " is-on" : "")} onClick={() => setGroup("")}>{tr("docs.all")} <small>{d.counts.total}</small></button>
        {d.tree.map((g: any) => <div key={g.key}>
          <button className={"doc-tree-item" + (group === g.key ? " is-on" : "")} onClick={() => setGroup(g.key)} data-testid={`doc-group-${g.key}`}>
            {lbl(g)} <small>{g.count}</small></button>
          {group === g.key && Object.entries(g.types).map(([k, n]: any) => <div key={k} className="doc-tree-sub">{lbl(typeOf(k))} · {n}</div>)}
        </div>)}
      </nav>
      <div className="doc-main">
        <div className="tmRow">
          <input className="ui-input" placeholder={tr("docs.search")} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && reload()} data-testid="doc-q"/>
          <select className="ui-input" value={status} onChange={e => setStatus(e.target.value)} data-testid="doc-status-filter">
            <option value="">{tr("docs.any_status")}</option>
            {tax.statuses.map((s: string) => <option key={s} value={s}>{tr(`docs.st_${s}` as Key)}</option>)}</select>
        </div>
        <div className="ui-panel"><table className="ui-table" data-testid="doc-table"><thead><tr>
          <th>{tr("docs.code")}</th><th>{tr("docs.title")}</th><th>{tr("docs.type")}</th><th>{tr("docs.status")}</th>
          <th>{tr("docs.agent_use")}</th><th>{tr("docs.review")}</th></tr></thead>
          <tbody>{d.items.length === 0 ? <tr><td colSpan={6}><EmptyState compact mood="chao" title={tr("docs.empty")}>{tr("docs.empty_hint")}</EmptyState></td></tr>
            : d.items.map((x: any) => <tr key={x.id} className={sel === x.id ? "is-selected" : ""} onClick={() => { setSel(x.id); setMode(""); }} style={{cursor: "pointer"}} data-testid={`doc-row-${x.id}`}>
              <td><code>{x.doc_code}</code></td>
              <td><b>{x.title}</b>{x.doc_class === "record" && <> <span className="ui-pill is-outline">{tr("docs.record")}</span></>}
                {x.pending_version && <><br/><small>{tr("docs.pending_v", {p0: x.pending_version.version_no, p1: tr(`docs.st_${x.pending_version.status}` as Key)})}</small></>}</td>
              <td>{getLocale() === "en" ? x.doc_type_en : x.doc_type_vi}</td>
              <td><StatusPill tone={toneOf(x.status === "published" ? "approved" : x.status)}>{tr(`docs.st_${x.status}` as Key)}</StatusPill>{x.version_no ? ` v${x.version_no}` : ""}</td>
              <td>{tr(`docs.use_${x.agent_use}` as Key)}{x.sensitivity !== "internal" && <><br/><small>{tr(`docs.sens_${x.sensitivity}` as Key)}</small></>}</td>
              <td><StatusPill tone={REVIEW_TONE[x.review_state]}>{tr(`docs.rv_${x.review_state}` as Key)}</StatusPill><br/><small>{day(x.review_due_at)}</small></td>
            </tr>)}</tbody></table></div>
        {sel && <DocDetail id={sel} can={can} onChanged={reload} onClose={() => setSel(null)}/>}
      </div>
    </div>
  </section>;
}

function TypeSelect({types, groups, value, onChange}: {types: any[]; groups: any[]; value: string; onChange: (v: string) => void}) {
  return <select className="ui-input" value={value} onChange={e => onChange(e.target.value)} data-testid="doc-type-pick">
    {groups.map(g => <optgroup key={g.key} label={lbl(g)}>
      {types.filter(t => t.group === g.key).map(t => <option key={t.key} value={t.key}>{lbl(t)}{t.doc_class === "record" ? ` (${tr("docs.record")})` : ""}</option>)}
    </optgroup>)}</select>;
}

function NewDoc({mode, companyId, types, groups, busy, onCancel, onDone, setError}: any) {
  const pos = useLoad(() => apiCompany.positions(companyId), [companyId]);
  const [f, setF] = useState<any>({title: "", doc_type: "policy", content: "", sensitivity: "", agent_use: "", customer_facing: false,
    owner_position_id: "", review_interval_days: "", effective_from: "", change_note: "", core_summary: ""});
  const [file, setFile] = useState<File | null>(null), [saving, setSaving] = useState(false);
  const toast = useToast();
  const ti = types.find((t: any) => t.key === f.doc_type) || {};
  async function save() {
    setSaving(true); setError(null);
    try {
      const common: any = {company_id: companyId, title: f.title, doc_type: f.doc_type, change_note: f.change_note,
        effective_from: f.effective_from || undefined, owner_position_id: f.owner_position_id ? Number(f.owner_position_id) : undefined};
      let r;
      if (mode === "upload") {
        if (!file) throw new Error(tr("docs.pick_file"));
        r = await apiDocs.upload(file, {...common, sensitivity: f.sensitivity, agent_use: f.agent_use});
      } else {
        r = await apiDocs.create({...common, content: f.content, customer_facing: f.customer_facing, core_summary: f.core_summary || undefined,
          sensitivity: f.sensitivity || undefined, agent_use: f.agent_use || undefined,
          review_interval_days: f.review_interval_days ? Number(f.review_interval_days) : undefined});
      }
      toast(tr("docs.created", {p0: r.doc_code})); onDone(r);
    } catch (e) { setError(e); } finally { setSaving(false); }
  }
  const positions: any[] = (pos.data as any)?.items || [];
  return <section className="ui-panel tm-card" data-testid="doc-form">
    <fieldset className="ui-form" disabled={busy || saving}>
      <FormRow>
        <Field label={tr("docs.title")}><input className="ui-input" value={f.title} onChange={e => setF({...f, title: e.target.value})} data-testid="df-title"/></Field>
        <Field label={tr("docs.type")} hint={ti.doc_class === "record" ? tr("docs.record_hint") : tr("docs.document_hint")}>
          <TypeSelect types={types} groups={groups} value={f.doc_type} onChange={v => setF({...f, doc_type: v})}/></Field>
        <Field label={tr("docs.owner_position")}><select className="ui-input" value={f.owner_position_id} onChange={e => setF({...f, owner_position_id: e.target.value})}>
          <option value="">—</option>{positions.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("docs.agent_use")} hint={tr(`docs.use_${f.agent_use || ti.agent_use}_hint` as Key)}>
          <select className="ui-input" value={f.agent_use} onChange={e => setF({...f, agent_use: e.target.value})} data-testid="df-use">
            <option value="">{tr("docs.default_x", {p0: tr(`docs.use_${ti.agent_use}` as Key)})}</option>
            {["core", "retrieve", "tool_only", "none"].map(u => <option key={u} value={u}>{tr(`docs.use_${u}` as Key)}</option>)}</select></Field>
        <Field label={tr("docs.sensitivity")}><select className="ui-input" value={f.sensitivity} onChange={e => setF({...f, sensitivity: e.target.value})}>
          <option value="">{tr("docs.default_x", {p0: tr(`docs.sens_${ti.sensitivity}` as Key)})}</option>
          {["public", "internal", "confidential", "restricted", "personal_data", "sensitive_personal_data"].map(s => <option key={s} value={s}>{tr(`docs.sens_${s}` as Key)}</option>)}</select></Field>
        <Field label={tr("docs.effective_from")}><input className="ui-input" type="date" value={f.effective_from} onChange={e => setF({...f, effective_from: e.target.value})}/></Field>
        {mode === "new" && <Field label={tr("docs.review_days")} hint={tr("docs.default_x", {p0: ti.review_days ?? "—"})}>
          <input className="ui-input" type="number" min={0} value={f.review_interval_days} onChange={e => setF({...f, review_interval_days: e.target.value})}/></Field>}
      </FormRow>
      {mode === "new" ? <Field label={tr("docs.content")} hint={tr("docs.content_hint")}>
        <textarea className="ui-input" rows={10} value={f.content} onChange={e => setF({...f, content: e.target.value})} data-testid="df-content"/></Field>
        : <Field label={tr("docs.file")} hint={tr("docs.file_hint")}><input type="file" accept=".pdf,.docx,.md,.txt,.csv,.html,.png,.jpg,.jpeg" onChange={e => setFile(e.target.files?.[0] || null)} data-testid="df-file"/></Field>}
      {mode === "new" && (f.agent_use || ti.agent_use) === "core" && <Field label={tr("docs.core_summary")} hint={tr("docs.core_summary_hint")}>
        <textarea className="ui-input" rows={3} maxLength={1200} value={f.core_summary} onChange={e => setF({...f, core_summary: e.target.value})} data-testid="df-summary"/></Field>}
      {mode === "new" && <label className="tmInline"><input type="checkbox" checked={f.customer_facing} onChange={e => setF({...f, customer_facing: e.target.checked})}/> {tr("docs.customer_facing")}</label>}
      <div className="tmRow" style={{marginTop: 10}}>
        <button className="ui-btn is-primary" onClick={save} data-testid="df-save">{ti.doc_class === "record" ? tr("docs.save_record") : tr("docs.save_draft")}</button>
        <button className="ui-btn is-ghost" onClick={onCancel}>{tr("docs.cancel")}</button>
      </div>
    </fieldset>
  </section>;
}

function DocDetail({id, can, onChanged, onClose}: {id: number; can: boolean; onChanged: () => void; onClose: () => void}) {
  const {data, error, reload, setError} = useLoad(() => apiDocs.get(id), [id]);
  const [draft, setDraft] = useState<string | null>(null), [note, setNote] = useState(""), [busy, setBusy] = useState(false);
  const [diff, setDiff] = useState<any>(null), [override, setOverride] = useState(false), [sum, setSum] = useState<string | null>(null);
  const toast = useToast();
  const d: any = data;
  const pend = d?.pending_version;
  useEffect(() => { setDraft(null); setDiff(null); setOverride(false); setSum(null); }, [id]);
  if (error && !data) return <ErrorBanner error={error} onRetry={reload}/>;
  if (!d) return <SkeletonRows n={3}/>;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(ok); setDraft(null); await reload(); onChanged(); return r; } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const editing = draft !== null;
  return <section className="ui-panel doc-detail" data-testid="doc-detail">
    <header className="ui-panel-head"><div className="ui-grow">
      <h2><code>{d.doc_code}</code> {d.title} {d.version_no ? <small>v{d.version_no}</small> : null}</h2>
      <p>{getLocale() === "en" ? d.doc_type_en : d.doc_type_vi} · {d.doc_class === "record" ? tr("docs.record_locked") : tr("docs.document")}
        {" · "}<StatusPill tone={toneOf(d.status === "published" ? "approved" : d.status)}>{tr(`docs.st_${d.status}` as Key)}</StatusPill></p></div>
      <button className="ui-btn is-ghost is-sm" onClick={onClose}>{tr("docs.close")}</button></header>
    <div className="ui-panel-body">
      {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
      <dl className="doc-meta" data-testid="doc-meta">
        <dt>{tr("docs.owner")}</dt><dd>{d.owner_position || d.owner || "—"}</dd>
        <dt>{tr("docs.agent_use")}</dt><dd>{tr(`docs.use_${d.agent_use}` as Key)}</dd>
        <dt>{tr("docs.sensitivity")}</dt><dd>{tr(`docs.sens_${d.sensitivity}` as Key)}{d.customer_facing ? ` · ${tr("docs.customer_facing")}` : ""}</dd>
        <dt>{tr("docs.effective")}</dt><dd>{day(d.effective_from)} → {d.effective_to ? day(d.effective_to) : tr("docs.open_ended")}</dd>
        <dt>{tr("docs.review")}</dt><dd><StatusPill tone={REVIEW_TONE[d.review_state]}>{tr(`docs.rv_${d.review_state}` as Key)}</StatusPill> {day(d.review_due_at)}{d.review_interval_days ? ` · ${tr("docs.every_n_days", {p0: d.review_interval_days})}` : ""}</dd>
        <dt>{tr("docs.retention")}</dt><dd>{d.retention_class ? tr(`docs.ret_${d.retention_class}` as Key) : "—"}{d.legal_hold ? ` · ${tr("docs.legal_hold")}` : ""}</dd>
        {d.file && <><dt>{tr("docs.file")}</dt><dd><button className="ui-btn is-ghost is-sm" onClick={() => apiDocs.file(d.file.id, d.file.filename).catch(setError)} data-testid="doc-download">{d.file.filename}</button> <small>sha256 {d.file.sha256.slice(0, 12)}…</small></dd></>}
      </dl>
      {!d.can_read ? <p className="is-warn" data-testid="doc-no-read">{tr("docs.no_read")}</p>
        : d.status === "published" || d.status === "superseded" || d.status === "archived" ? <>
          <h3 className="ops-cat">{tr("docs.current_content")}</h3>
          <pre className="doc-content" data-testid="doc-content">{d.content || tr("docs.no_text")}</pre>
          {d.agent_use === "core" && <><h3 className="ops-cat">{tr("docs.core_summary")}</h3>
            <p className="tmGuide" data-testid="doc-summary">{d.core_summary || tr("docs.core_summary_auto")}</p></>}</> : null}
      {(d.flags || []).some((f: any) => f.status === "open") && <div className="tm-card doc-pending" data-testid="doc-flags">
        <h3 className="ops-cat">{tr("docs.flags_open")}</h3>
        {(d.flags || []).filter((f: any) => f.status === "open").map((f: any) => <div key={f.id} className="tmRow">
          <span className="ui-pill is-wait">{tr(`docs.flag_${f.reason}` as Key)}</span><span className="ui-grow">{f.member || "—"} · v{f.version_no}: {f.note}</span>
          {can && <><button className="ui-btn is-ghost is-sm" onClick={() => run(() => apiDocs.flagStatus(d.id, f.id, "resolved"), tr("docs.saved"))}>{tr("docs.flag_resolve")}</button>
            <button className="ui-btn is-ghost is-sm" onClick={() => run(() => apiDocs.flagStatus(d.id, f.id, "dismissed"), tr("docs.saved"))}>{tr("docs.flag_dismiss")}</button></>}
        </div>)}</div>}

      {pend && <div className="tm-card doc-pending" data-testid="doc-pending">
        <h3 className="ops-cat">{tr("docs.pending_v", {p0: pend.version_no, p1: tr(`docs.st_${pend.status}` as Key)})}</h3>
        {pend.change_note && <p><small>{pend.change_note}</small></p>}
        {(pend.conflicts || []).length > 0 && <div className="is-warn" data-testid="doc-conflicts"><b>{tr("docs.conflicts", {p0: pend.conflicts.length})}</b>
          <ul>{pend.conflicts.map((c: any, i: number) => <li key={i}>{c.label}: <b>{c.value}</b> ≠ {c.other_value} ({c.other_source})</li>)}</ul></div>}
        {pend.status === "draft" && can && d.agent_use === "core" && <Field label={tr("docs.core_summary")} hint={tr("docs.core_summary_hint")}>
          <textarea className="ui-input" rows={3} maxLength={1200} value={sum ?? pend.core_summary ?? ""} onChange={e => setSum(e.target.value)} data-testid="doc-summary-edit"/></Field>}
        {pend.status === "draft" && can ? <>
          <textarea className="ui-input" rows={8} value={draft ?? pend.content ?? ""} onChange={e => setDraft(e.target.value)} data-testid="doc-draft-text"/>
          <div className="tmRow">
            {(editing || sum !== null) && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.editVersion(d.id, pend.id, {...(editing ? {content: draft} : {}), ...(sum !== null ? {core_summary: sum} : {})}), tr("docs.saved"))}>{tr("docs.save_draft")}</button>}
            <button className="ui-btn is-primary is-sm" disabled={busy || editing || sum !== null} onClick={() => run(() => apiDocs.submit(d.id, pend.id), tr("docs.submitted"))} data-testid="doc-submit">{tr("docs.submit")}</button>
          </div></> : <pre className="doc-content">{pend.content}</pre>}
        {pend.status === "in_review" && <p>{tr("docs.waiting_for", {p0: pend.approver || "—"})}</p>}
        {pend.status === "approved" && <p>{tr("docs.approved_until", {p0: day(pend.effective_from)})}</p>}
        {d.i_can_approve && <div className="tmRow">
          <input className="ui-input" placeholder={tr("docs.note")} value={note} onChange={e => setNote(e.target.value)}/>
          {(pend.conflicts || []).length > 0 && <label className="tmInline"><input type="checkbox" checked={override} onChange={e => setOverride(e.target.checked)} data-testid="doc-override"/> {tr("docs.override")}</label>}
          <button className="ui-btn is-primary is-sm" disabled={busy || ((pend.conflicts || []).length > 0 && !override)} onClick={() => run(() => apiDocs.decide(d.id, pend.id, "approved", note, override), tr("docs.approved_ok"))} data-testid="doc-approve">{tr("docs.approve")}</button>
          <button className="ui-btn is-danger is-sm" disabled={busy} onClick={() => run(() => apiDocs.decide(d.id, pend.id, "rejected", note), tr("docs.rejected_ok"))} data-testid="doc-reject">{tr("docs.reject")}</button>
        </div>}
      </div>}

      {can && <div className="tmRow" style={{marginTop: 10}}>
        {d.doc_class === "document" && !pend && ["published", "draft", "in_review"].includes(d.status) && d.can_read &&
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.newVersion(d.id, {content: d.content || "…", change_note: ""}), tr("docs.version_started"))} data-testid="doc-new-version">{tr("docs.new_version")}</button>}
        {d.status === "published" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.review(d.id), tr("docs.reviewed_ok"))} data-testid="doc-mark-reviewed">{tr("docs.mark_reviewed")}</button>}
        {!["archived", "disposed"].includes(d.status) && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.archive(d.id), tr("docs.archived_ok"))}>{tr("docs.archive")}</button>}
      </div>}

      <h3 className="ops-cat">{tr("docs.history")}</h3>
      <table className="ui-table" data-testid="doc-versions"><thead><tr><th>v</th><th>{tr("docs.status")}</th><th>{tr("docs.author")}</th>
        <th>{tr("docs.approved_by")}</th><th>{tr("docs.change_note")}</th><th/></tr></thead>
        <tbody>{(d.versions || []).map((v: any) => <tr key={v.id}><td>v{v.version_no}</td>
          <td><StatusPill tone={toneOf(v.status === "published" ? "approved" : v.status)}>{tr(`docs.st_${v.status}` as Key)}</StatusPill></td>
          <td>{v.author || "—"}</td><td>{v.approved_by || (v.status === "in_review" ? `→ ${v.approver || "—"}` : "—")}<br/><small>{day(v.approved_at || v.published_at)}</small></td>
          <td><small>{v.change_note}{v.review_note ? ` · ${v.review_note}` : ""}</small></td>
          <td>{v.version_no > 1 && d.can_read && <button className="ui-btn is-ghost is-sm" onClick={() => apiDocs.diff(d.id, v.version_no - 1, v.version_no).then(setDiff).catch(setError)} data-testid={`doc-diff-${v.version_no}`}>{tr("docs.diff")}</button>}</td>
        </tr>)}</tbody></table>
      {diff && <div className="doc-diff" data-testid="doc-diff">
        <p><b>v{diff.from} → v{diff.to}</b> · +{diff.added} / −{diff.removed}</p>
        <pre className="doc-content">{diff.lines.map((ln: string, i: number) => <span key={i} className={ln.startsWith("+") && !ln.startsWith("+++") ? "is-add" : ln.startsWith("-") && !ln.startsWith("---") ? "is-del" : ""}>{ln + "\n"}</span>)}</pre>
      </div>}
    </div>
  </section>;
}

/* M3b — Sự kiện công ty: số liệu chính thức có nguồn (trích từ tài liệu đã ban hành / nhập tay), mâu thuẫn giữa nguồn. */
export function FactsTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => companyId ? apiDocs.facts(companyId) : Promise.resolve(null), [companyId]);
  const [f, setF] = useState({key: "return_window_days", value: ""}), [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="facts-error"/>;
  if (!data) return <SkeletonRows n={4} h={36}/>;
  const d: any = data;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); await reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const en = getLocale() === "en";
  return <section className="ui-section" data-testid="facts">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("docs.facts_explain")}</p>
    <div className="tmRow"><span className={"ui-pill" + (d.conflicts ? " is-risk" : " is-ok")}>{tr("docs.facts_conflicts")}: <b>{d.conflicts}</b></span></div>
    <div className="ui-panel"><table className="ui-table" data-testid="facts-table"><thead><tr>
      <th>{tr("docs.fact")}</th><th>{tr("docs.fact_value")}</th><th>{tr("docs.fact_source")}</th><th/></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={4}><small>{tr("docs.facts_empty")}</small></td></tr>
        : d.items.flatMap((it: any) => it.sources.map((x: any, i: number) => <tr key={x.id} className={it.conflict ? "is-warn" : ""}>
          <td>{i === 0 ? <><b>{en ? it.label_en : it.label_vi}</b>{it.conflict && <> <StatusPill tone="risk">{tr("docs.conflict")}</StatusPill></>}</> : ""}</td>
          <td><b>{x.value}</b> {x.unit}</td><td>{x.source}<br/><small>{x.excerpt}</small></td>
          <td>{can && x.source_kind === "manual" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.delFact(x.id), tr("docs.saved"))}>{tr("docs.remove")}</button>}</td>
        </tr>))}</tbody></table></div>
    {can && <><h3 className="ops-cat">{tr("docs.fact_manual")}</h3>
      <FormRow>
        <Field label={tr("docs.fact")}><select className="ui-input" value={f.key} onChange={e => setF({...f, key: e.target.value})} data-testid="fact-key">
          {d.keys.map((k: any) => <option key={k.key} value={k.key}>{en ? k.en : k.vi}</option>)}</select></Field>
        <Field label={tr("docs.fact_value")}><input className="ui-input" value={f.value} onChange={e => setF({...f, value: e.target.value})} data-testid="fact-value"/></Field>
      </FormRow>
      <button className="ui-btn is-primary" disabled={busy || !f.value} onClick={() => run(() => apiDocs.putFact({company_id: companyId, ...f}), tr("docs.saved"))} data-testid="fact-save">{tr("docs.fact_save")}</button></>}
  </section>;
}

/* M3d — Hồ sơ bắt buộc & lưu trữ: danh mục theo điều kiện công ty (loại hình, số lao động là người, DLCN, ngành) với căn cứ
   + "cần kiểm tra"; hạn lưu trữ tự tính, huỷ hồ sơ hết hạn (chỉ chủ, giữ hash). Lịch tham khảo, không phải tư vấn pháp lý. */
const REQ_TONE: Record<string, any> = {ok: "ok", missing: "risk", na: "neutral"};
const PACKS = ["all", "employees", "personal_data", "shop", "agency", "ketoan"] as const;
export function RecordsTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => companyId
    ? Promise.all([apiDocs.requirements(companyId), apiDocs.list(companyId, {status: "published"})]) : Promise.resolve(null), [companyId]);
  const [nf, setNf] = useState({name: "", level: "required", legal_basis: ""}), [pick, setPick] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false), [showNa, setShowNa] = useState(false);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="records-error"/>;
  if (!data) return <SkeletonRows n={6} h={36}/>;
  const [ev, lib]: any = data;
  const en = getLocale() === "en";
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); await reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const f = ev.facts, items: any[] = ev.items.filter((i: any) => showNa || i.status !== "na");
  const statusKey = (s: string) => ("docs.req_" + s) as Key;
  return <section className="ui-section" data-testid="records">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="records-save-error"/> : null}
    <div className="ui-banner" data-testid="records-disclaimer">⚖ {en ? ev.disclaimer_en : ev.disclaimer_vi}</div>
    <p className="tmGuide">{tr("docs.req_explain")}</p>
    <div className="tmRow" data-testid="records-stats">
      <span className={"ui-pill" + (ev.required_ok === ev.required_total ? " is-ok" : " is-risk")}>{tr("docs.req_required")}: <b>{ev.required_ok}/{ev.required_total}</b></span>
      <span className="ui-pill">{tr("docs.req_humans")}: <b>{f.humans}</b></span>
      <span className="ui-pill">{tr("docs.req_entity")}: <b>{f.entity_type || "—"}</b></span>
      <span className="ui-pill">{tr("docs.req_pd")}: <b>{f.personal_data ? tr("docs.yes") : tr("docs.no")}</b></span>
      {f.templates.length > 0 && <span className="ui-pill">{tr("docs.req_industry")}: <b>{f.templates.join(", ")}</b></span>}
      <label style={{display: "inline-flex", gap: 6, alignItems: "center"}}><input type="checkbox" checked={showNa} onChange={e => setShowNa(e.target.checked)} data-testid="records-show-na"/> {tr("docs.req_show_na")}</label>
    </div>
    {PACKS.map(pk => {
      const rows = items.filter(i => i.pack === pk);
      if (!rows.length) return null;
      return <div key={pk} className="ui-panel"><h3 className="ops-cat">{tr(("docs.pack_" + pk) as Key)}</h3>
        <table className="ui-table req-table" data-testid={"records-" + pk}><thead><tr>
          <th>{tr("docs.req_item")}</th><th>{tr("docs.req_status")}</th><th>{tr("docs.req_basis")}</th><th>{tr("docs.req_docs")}</th></tr></thead>
          <tbody>{rows.map(i => <tr key={i.id} data-testid={"req-" + i.key} className={i.status === "missing" && i.level === "required" ? "is-warn" : ""}>
            <td><b>{en ? i.name_en : i.name}</b><br/>
              <StatusPill tone={i.level === "required" ? "wait" : "neutral"}>{tr(i.level === "required" ? "docs.req_level_required" : "docs.req_level_recommended")}</StatusPill>
              {i.needs_review && <> <StatusPill tone="wait">{tr("docs.req_to_verify")}</StatusPill></>}
              {i.source === "custom" && <> <StatusPill tone="neutral">{tr("docs.req_custom")}</StatusPill></>}
              <small className="req-basis-m">{i.legal_basis}</small></td>
            <td><StatusPill tone={REQ_TONE[i.status]}>{tr(statusKey(i.status))}</StatusPill>{(i.why_code || i.why) && <><br/><small>{i.why_code ? tr(("docs.why_" + i.why_code) as Key, i.why_params || {}) : i.why}</small></>}</td>
            <td><small>{i.legal_basis}</small></td>
            <td>{i.documents.map((x: any) => <div key={x.doc_code}><code className="doc-code">{x.doc_code}</code> <small>{x.title_key ? tr(("docs." + x.title_key) as Key) : x.title}</small></div>)}
              {can && i.status === "missing" && <div className="tmRow">
                <select className="ui-input" value={pick[i.id] || ""} onChange={e => setPick({...pick, [i.id]: e.target.value})} data-testid={"req-pick-" + i.key}>
                  <option value="">{tr("docs.req_attach_pick")}</option>
                  {lib.items.map((x: any) => <option key={x.id} value={x.id}>{x.doc_code} · {x.title}</option>)}</select>
                <button className="ui-btn is-ghost is-sm" disabled={busy || !pick[i.id]} onClick={() => run(() => apiDocs.attachRequirement(i.id, Number(pick[i.id])), tr("docs.saved"))}>{tr("docs.req_attach")}</button>
              </div>}
              {can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiDocs.editRequirement(i.id, {enabled: !i.enabled}), tr("docs.saved"))}>
                {tr(i.enabled ? "docs.req_disable" : "docs.req_enable")}</button>}</td>
          </tr>)}</tbody></table></div>;
    })}
    {can && <><h3 className="ops-cat">{tr("docs.req_add")}</h3>
      <FormRow>
        <Field label={tr("docs.req_item")}><input className="ui-input" value={nf.name} onChange={e => setNf({...nf, name: e.target.value})} data-testid="req-new-name"/></Field>
        <Field label={tr("docs.req_level")}><select className="ui-input" value={nf.level} onChange={e => setNf({...nf, level: e.target.value})}>
          <option value="required">{tr("docs.req_level_required")}</option><option value="recommended">{tr("docs.req_level_recommended")}</option></select></Field>
        <Field label={tr("docs.req_basis")}><input className="ui-input" value={nf.legal_basis} onChange={e => setNf({...nf, legal_basis: e.target.value})}/></Field>
      </FormRow>
      <button className="ui-btn is-primary" disabled={busy || !nf.name.trim()} data-testid="req-new-save"
        onClick={() => run(() => apiDocs.addRequirement({company_id: companyId, ...nf, needs_review: true}), tr("docs.saved")).then(() => setNf({name: "", level: "required", legal_basis: ""}))}>{tr("docs.req_add_btn")}</button></>}
    <h3 className="ops-cat">{tr("docs.ret_title")}</h3>
    <p className="tmGuide">{tr("docs.ret_explain")}</p>
    <div className="ui-panel"><table className="ui-table" data-testid="retention-table"><thead><tr>
      <th>{tr("docs.code")}</th><th>{tr("docs.title")}</th><th>{tr("docs.retention")}</th><th>{tr("docs.ret_until")}</th><th/></tr></thead>
      <tbody>{ev.retention.items.length === 0 ? <tr><td colSpan={5}><small>{tr("docs.ret_empty")}</small></td></tr>
        : ev.retention.items.map((x: any) => <tr key={x.id} className={x.due ? "is-warn" : ""}>
          <td><code className="doc-code">{x.doc_code}</code></td><td>{x.title}</td><td><small>{x.retention_class}</small></td>
          <td>{day(x.retain_until)}{x.legal_hold && <> <StatusPill tone="wait">{tr("docs.legal_hold")}</StatusPill></>}{x.due && <> <StatusPill tone="risk">{tr("docs.ret_due")}</StatusPill></>}</td>
          <td>{can && x.due && <button className="ui-btn is-danger is-sm" disabled={busy} data-testid={"dispose-" + x.id}
            onClick={() => { if (window.confirm(tr("docs.ret_confirm"))) run(() => apiDocs.dispose(x.id, "UI"), tr("docs.ret_disposed")); }}>{tr("docs.ret_dispose")}</button>}</td>
        </tr>)}</tbody></table></div>
  </section>;
}
