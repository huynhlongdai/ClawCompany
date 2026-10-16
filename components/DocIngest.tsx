"use client";
// M3c — Công ty › Tài liệu & tri thức › Nạp tài liệu: tải tệp (PDF/ảnh scan có OCR, DOCX, XLSX, PPTX, MD…), từ URL,
// "Tạo từ mẫu" (mẫu VN thường gặp), nguồn đồng bộ Google Drive / Notion / URL. Mọi tài liệu nạp vào là NHÁP chờ duyệt;
// phân loại + trích hồ sơ pháp nhân chỉ là ĐỀ XUẤT (admin bấm Áp dụng mới ghi vào hồ sơ).
import {useState} from "react";
import {apiIngest} from "../lib/api";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {fmtMoney, getLocale, t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

const IM_TONE: Record<string, any> = {done: "ok", duplicate: "wait", empty: "risk", error: "risk"};
const SRC_TONE: Record<string, any> = {active: "ok", needs_account: "wait", error: "risk", paused: "neutral"};
const PROFILE_FIELDS = ["legal_name", "tax_code", "founded_on", "legal_representative", "registered_address", "charter_capital_vnd"];
const vnd = (n: number) => fmtMoney(n, "VND");
const when = (s?: string | null) => s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString(getLocale() === "en" ? "en-GB" : "vi-VN") : "—";

export function DocIngestTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => companyId ? apiIngest.list(companyId) : Promise.resolve(null), [companyId]);
  const [file, setFile] = useState<File | null>(null), [asRecord, setAsRecord] = useState(false);
  const [url, setUrl] = useState(""), [busy, setBusy] = useState(false), [last, setLast] = useState<any>(null);
  const [src, setSrc] = useState<any>({kind: "notion", name: "", ref: "", credential: ""});
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="ingest-error"/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { const r = await fn(); if (r?.import) setLast(r.import); toast(ok); await reload(); return r; }
    catch (e) { setError(e); await reload(); } finally { setBusy(false); }
  }
  const ocr = d.ocr || {};
  return <section className="ui-section" data-testid="doc-ingest">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="ingest-save-error"/> : null}
    <p className="tmGuide">{tr("ingest.explain")}</p>
    <div className="tmRow" data-testid="ingest-ocr">
      <span className={"ui-pill" + (ocr.tesseract ? " is-ok" : " is-wait")}>OCR: <b>{ocr.tesseract ? (ocr.vie ? tr("ingest.ocr_vie") : tr("ingest.ocr_eng")) : tr("ingest.ocr_off")}</b></span>
    </div>

    {can && <div className="ui-panel ingest-grid">
      <div data-testid="ingest-file">
        <h4>{tr("ingest.file_title")}</h4>
        <p><small>{tr("ingest.file_hint")}</small></p>
        <input type="file" className="ui-input" onChange={e => setFile(e.target.files?.[0] || null)} data-testid="ingest-file-input"
          accept=".pdf,.docx,.xlsx,.pptx,.md,.txt,.csv,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff,.webp"/>
        <label className="ui-check"><input type="checkbox" checked={asRecord} onChange={e => setAsRecord(e.target.checked)}/> {tr("ingest.as_record")}</label>
        <button className="ui-btn is-primary is-sm" disabled={!file || busy} data-testid="ingest-file-go"
          onClick={() => file && run(() => apiIngest.file(file, {company_id: companyId, doc_class: asRecord ? "record" : ""}), tr("ingest.done"))}>{tr("ingest.import")}</button>
      </div>
      <div data-testid="ingest-url">
        <h4>{tr("ingest.url_title")}</h4>
        <p><small>{tr("ingest.url_hint")}</small></p>
        <input className="ui-input" placeholder="https://…" value={url} onChange={e => setUrl(e.target.value)} data-testid="ingest-url-input"/>
        <button className="ui-btn is-ghost is-sm" disabled={!url || busy} data-testid="ingest-url-go"
          onClick={() => run(() => apiIngest.url({company_id: companyId, url}), tr("ingest.done"))}>{tr("ingest.import")}</button>
      </div>
    </div>}

    {last && <ImportCard im={last} title={tr("ingest.last")}/>}

    <h3>{tr("ingest.tpl_title")}</h3>
    <p className="tmGuide"><small>{tr("ingest.tpl_hint")}</small></p>
    <div className="ingest-tpls" data-testid="ingest-templates">
      {d.templates.map((t: any) => <div key={t.key} className="ui-panel ingest-tpl" data-testid={`tpl-${t.key}`}>
        <b>{getLocale() === "en" ? t.en : t.vi}</b>
        <small>{tr("ingest.basis")}: {t.basis}</small>
        {can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiIngest.template({company_id: companyId, key: t.key}), tr("ingest.tpl_done"))}>{tr("ingest.tpl_use")}</button>}
      </div>)}
    </div>

    <h3>{tr("ingest.src_title")}</h3>
    <p className="tmGuide"><small>{tr("ingest.src_hint")}</small></p>
    <div className="ui-panel"><table className="ui-table" data-testid="ingest-sources"><thead><tr>
      <th>{tr("ingest.src_name")}</th><th>{tr("ingest.src_kind")}</th><th>{tr("ingest.status")}</th><th>{tr("ingest.src_last")}</th><th/></tr></thead>
      <tbody>{d.sources.length === 0 ? <tr><td colSpan={5}><small>{tr("ingest.src_empty")}</small></td></tr>
        : d.sources.map((s: any) => <tr key={s.id} data-testid={`src-${s.id}`}>
          <td><b>{s.name || s.kind}</b>{s.has_credential && <><br/><small>{tr("ingest.token")} {s.credential_hint}</small></>}</td>
          <td>{tr(`ingest.kind_${s.kind}` as Key)}</td>
          <td><StatusPill tone={SRC_TONE[s.status]}>{tr(`ingest.src_${s.status}` as Key)}</StatusPill>
            {s.last_error && <><br/><small className="ui-text-risk">{s.last_error.slice(0, 160)}</small></>}</td>
          <td><small>{when(s.last_synced_at)}</small></td>
          <td>{can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiIngest.syncSource(s.id), tr("ingest.synced"))}>{tr("ingest.sync")}</button>}</td>
        </tr>)}</tbody></table></div>
    {can && <div className="ui-panel" data-testid="ingest-src-new">
      <FormRow>
        <Field label={tr("ingest.src_kind")}><select className="ui-input" value={src.kind} onChange={e => setSrc({...src, kind: e.target.value})}>
          {["notion", "gdrive", "url"].map(k => <option key={k} value={k}>{tr(`ingest.kind_${k}` as Key)}</option>)}</select></Field>
        <Field label={tr("ingest.src_name")}><input className="ui-input" value={src.name} onChange={e => setSrc({...src, name: e.target.value})}/></Field>
      </FormRow>
      <FormRow>
        <Field label={tr(`ingest.ref_${src.kind}` as Key)}><input className="ui-input" value={src.ref} onChange={e => setSrc({...src, ref: e.target.value})}/></Field>
        {src.kind !== "url" && <Field label={tr(`ingest.cred_${src.kind}` as Key)}><input className="ui-input" type="password" autoComplete="off" value={src.credential}
          onChange={e => setSrc({...src, credential: e.target.value})} placeholder={tr("ingest.cred_ph")}/></Field>}
      </FormRow>
      <button className="ui-btn is-primary is-sm" disabled={busy || !src.ref} data-testid="ingest-src-save"
        onClick={() => run(() => apiIngest.addSource({company_id: companyId, kind: src.kind, name: src.name,
          config: src.kind === "url" ? {url: src.ref} : src.kind === "gdrive" ? {folder_id: src.ref} : {page_ids: src.ref.split(/[\s,]+/).filter(Boolean)},
          credential: src.credential || undefined}).then(r => { setSrc({kind: src.kind, name: "", ref: "", credential: ""}); return r; }), tr("ingest.src_saved"))}>{tr("ingest.src_add")}</button>
    </div>}

    <h3>{tr("ingest.history")}</h3>
    {d.items.length === 0 ? <EmptyState compact mood="chao" title={tr("ingest.empty")}>{tr("ingest.empty_hint")}</EmptyState>
      : d.items.map((im: any) => <ImportCard key={im.id} im={im} onDecide={async (action: string) => {
          await run(() => apiIngest.proposals(im.id, action), action === "apply" ? tr("ingest.applied") : tr("ingest.dismissed"));
        }} canApply={!!caps?.manage_roles}/>)}
  </section>;
}

function ImportCard({im, title, onDecide, canApply}: {im: any; title?: string; onDecide?: (a: string) => void; canApply?: boolean}) {
  const s = im.suggestions || {}, prof = (im.proposals || {}).company_profile;
  return <div className="ui-panel ingest-card" data-testid={`import-${im.id}`}>
    {title && <h4>{title}</h4>}
    <div className="tmRow">
      <StatusPill tone={IM_TONE[im.status]}>{tr(`ingest.st_${im.status}` as Key)}</StatusPill>
      <b>{im.filename || im.source_ref}</b>
      <small>{tr(`ingest.from_${im.source}` as Key)} · {im.method}{im.ocr_used ? " · OCR" : ""} · {tr("ingest.chars", {p0: im.extracted_chars})}</small>
      <span className="ui-grow"/>
      {im.document && <span className="ui-pill"><code>{im.document.doc_code}</code> {im.document.title} · {tr(`docs.st_${im.document.status}` as Key)}</span>}
      {im.duplicate_of && <span className="ui-pill is-wait">{tr("ingest.dup_of")} <code>{im.duplicate_of.doc_code}</code></span>}
    </div>
    {im.note && <p><small>{im.note_code ? tr(("ingest.note_" + im.note_code) as Key, im.note_params || {}) : im.note}</small></p>}
    {s.doc_type && <p><small>{tr("ingest.suggest", {p0: (getLocale() === "en" ? s.doc_type_en : s.doc_type_vi) || s.doc_type,
      p1: s.doc_type_reason === "phrase" ? tr("ingest.reason_phrase", {p0: s.doc_type_hit}) : tr(`ingest.reason_${s.doc_type_reason || "default"}` as Key),
      p2: tr(`docs.sens_${s.sensitivity}` as Key), p3: tr(`docs.use_${s.agent_use}` as Key)})}
      {s.sensitivity_reason === "pii" ? " — " + tr("ingest.pii", {p0: s.pii?.cccd ?? 0, p1: s.pii?.phone ?? 0, p2: s.pii?.email ?? 0}) : ""}
      {s.effective_from ? " · " + tr("ingest.effective", {p0: s.effective_from}) : ""}</small></p>}
    {prof && <div className="ingest-prop" data-testid={`import-prop-${im.id}`}>
      <b>{tr("ingest.prop_title")}</b> <StatusPill tone={im.proposals_status === "applied" ? "ok" : im.proposals_status === "pending" ? "wait" : "neutral"}>{tr(`ingest.prop_${im.proposals_status || "none"}` as Key)}</StatusPill>
      <dl className="ingest-dl">{PROFILE_FIELDS.filter(k => prof[k] != null).map(k => <div key={k}><dt>{tr(`ingest.f_${k}` as Key)}</dt>
        <dd>{k === "charter_capital_vnd" ? vnd(prof[k]) : String(prof[k])}</dd></div>)}</dl>
      {onDecide && im.proposals_status === "pending" && canApply && <div className="tmRow">
        <button className="ui-btn is-primary is-sm" onClick={() => onDecide("apply")} data-testid={`prop-apply-${im.id}`}>{tr("ingest.apply")}</button>
        <button className="ui-btn is-ghost is-sm" onClick={() => onDecide("dismiss")}>{tr("ingest.dismiss")}</button></div>}
    </div>}
  </div>;
}
