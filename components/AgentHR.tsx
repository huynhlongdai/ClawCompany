"use client";
// M3 — Nhân sự AI: danh sách đối chiếu gateway + wizard tuyển 4 bước (tab "Nhân sự AI"
// của /app/team), và bảng điều khiển trên /app/agents/[id]: sửa hồ sơ ghi 2 chiều,
// vòng đời (tạm dừng / tiếp tục / cho nghỉ), lệch & "Đồng bộ lại", quyền tool theo seat.
import {useEffect, useMemo, useState} from "react";
import Link from "next/link";
import {apiAgentsHR, apiMcp, apiTeam, errorText} from "../lib/api";
import {t as tr, lazy} from "../lib/i18n";

export const LIFECYCLE_VI: Record<string, string> = lazy(() => ({
  active: tr("agentHr.dang_lam"), paused: tr("agentHr.tam_dung"), retired: tr("agentHr.da_nghi"), runtime_missing: tr("agentHr.cho_gateway"),
  provisioning: tr("agentHr.dang_tao"), runtime_error: tr("agentHr.loi_tao"), detached: tr("agentHr.mat_tren_gateway"),
}));
const LIFECYCLE_CLS: Record<string, string> = {active: "is-ok", paused: "is-wait", retired: "is-outline", runtime_missing: "is-wait",
  runtime_error: "is-risk", detached: "is-risk", provisioning: "is-info"};
const FILE_VI: Record<string, string> = lazy(() => ({in_sync: tr("agentHr.khop"), edited_on_gateway: tr("agentHr.bi_sua_tren_gateway"),
  missing_on_gateway: tr("agentHr.mat_tren_gateway"), untracked: tr("agentHr.chua_co_ban_clawcompany"), absent: tr("agentHr.chua_co"), no_agent: tr("agentHr.khong_co_agent"), error: tr("agentHr.loi_doc")}));
const LEVEL_VI: Record<string, string> = lazy(() => ({allowed: tr("agentHr.cho_phep"), ask: tr("agentHr.hoi_duyet"), off: tr("agentHr.tat")}));

function Pill({lc}: {lc: string}) {
  return <span className={`ui-pill ${LIFECYCLE_CLS[lc] ?? "is-wait"}`} data-testid="hr-lifecycle">{LIFECYCLE_VI[lc] || lc}</span>;
}

// ------------------------------------------------------------------ tab: danh sách + tuyển

export function AgentHRTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const [roster, setRoster] = useState<any>(null), [error, setError] = useState("");
  const [wizard, setWizard] = useState(false);
  async function load() {
    try { setRoster(await apiAgentsHR.roster(companyId)); } catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => { load(); }, [companyId]);
  if (error) return <div className="ui-banner is-error">{error}</div>;
  if (!roster) return <div className="ui-empty">{tr("agentHr.dang_tai")}</div>;
  const c = roster.counts || {};
  return <div className="hrWrap">
    <section className="ui-panel ui-panel-body">
      <div className="lab-cardhead"><div><b>{tr("agentHr.nhan_su_ai")}</b>
        <span>{roster.items.length} agent · {c.active || 0} {tr("agentHr.dang_lam_2")}{c.paused ? tr("agentHr.tam_dung_2", {p0: c.paused}) : ""}{c.retired ? tr("agentHr.da_nghi_2", {p0: c.retired}) : ""}{c.runtime_missing ? tr("agentHr.cho_gateway_2", {p0: c.runtime_missing}) : ""}</span></div>
        {caps.invite && <button className="ui-btn is-primary" onClick={() => setWizard(true)} data-testid="hr-hire-open">{tr("agentHr.tuyen_nhan_su_ai")}</button>}
      </div>
      {roster.gateway_error && <div className="ui-banner is-error">{tr("agentHr.khong_doc_duoc_gateway")} {roster.gateway_error}</div>}
      {roster.unbound_on_gateway > 0 && <small className="tmGuide">{roster.unbound_on_gateway} {tr("agentHr.agent_tren_gateway_chua_gan")}</small>}
      <div className="hrScroll"><table className="ui-table" data-testid="hr-roster"><thead><tr>
        <th>{tr("agentHr.ten")}</th><th>{tr("agentHr.phong_ban_quan_ly")}</th><th>Model</th><th>{tr("agentHr.trang_thai")}</th><th>Gateway</th></tr></thead>
        <tbody>{roster.items.map((a: any) => <tr key={a.agent_id} className={a.lifecycle === "retired" ? "is-off" : ""}>
          <td><Link href={`/app/agents/${a.member_id}`}><b>{a.name}</b></Link><br/><small>{a.role}{a.is_head ? tr("agentHr.truong_phong") : ""}</small></td>
          <td><small>{a.department || tr("agentHr.ban_dieu_hanh")}<br/>{a.manager ? tr("agentHr.bao_cao", {p0: a.manager}) : "—"}</small></td>
          <td><small>{a.model || a.gateway_model || "—"}</small></td>
          <td><Pill lc={a.lifecycle}/></td>
          <td><small>{a.on_gateway === null ? "?" : a.on_gateway ? tr("agentHr.co_phien", {p0: a.sessions, p1: a.running ? tr("agentHr.dang_chay_hau_to") : ""}) : a.lifecycle === "retired" ? tr("agentHr.da_go") : <span className="is-warn">{tr("agentHr.khong_co")}</span>}</small></td>
        </tr>)}</tbody></table></div>
      {!roster.items.length && <div className="ui-empty">{tr("agentHr.chua_co_nhan_su_ai")}{caps.invite ? tr("agentHr.bam_tuyen_nhan_su_ai") : "."}</div>}
    </section>
    {wizard && <HireWizard companyId={companyId} onClose={() => setWizard(false)} onDone={load}/>}
  </div>;
}

const STEPS = lazy(() => ([tr("agentHr.vai_tro"), tr("agentHr.phong_ban"), tr("agentHr.model_ngan_sach"), tr("agentHr.tinh_cach")]));

function HireWizard({companyId, onClose, onDone}: {companyId: number | null; onClose: () => void; onDone: () => void}) {
  const [opt, setOpt] = useState<any>(null), [step, setStep] = useState(0), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [result, setResult] = useState<any>(null);
  const [f, setF] = useState<any>({name: "", role: "", job_description: "", department_id: "", manager_member_id: "",
    model: "", monthly_budget: "", personality: "tan-tuy", emoji: "", manager_notes: ""});
  const set = (k: string, v: any) => setF((x: any) => ({...x, [k]: v}));
  useEffect(() => { apiAgentsHR.options().then(o => {
    setOpt(o); const d = (o.models || []).find((m: any) => m.default) || (o.models || [])[0];
    setF((x: any) => ({...x, model: d?.id || "", personality: o.default_personality || "tan-tuy"}));
  }).catch(e => setError(errorText(e))); }, []);
  const cid = companyId || opt?.companies?.[0]?.id || null;
  const depts = (opt?.departments || []).filter((d: any) => d.company_id === cid);
  const dept = depts.find((d: any) => String(d.id) === String(f.department_id));
  const managers = (opt?.managers || []).filter((m: any) => m.company_id === cid);
  const head = dept?.head_member_id ? managers.find((m: any) => m.id === dept.head_member_id) : null;
  const userLen = (f.manager_notes || "").length;
  const canNext = [f.name.trim().length > 0, true, !(Number(f.monthly_budget) < 0), userLen <= 3000][step];
  async function submit() {
    setBusy(true); setError("");
    try {
      const r = await apiAgentsHR.hire({...f, company_id: cid, department_id: f.department_id ? Number(f.department_id) : null,
        manager_member_id: f.manager_member_id ? Number(f.manager_member_id) : null,
        monthly_budget: f.monthly_budget === "" ? null : Number(f.monthly_budget)});
      setResult(r); onDone();
    } catch (e: any) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <section className="ui-panel ui-panel-body hrWizard" data-testid="hr-wizard">
    <div className="lab-cardhead"><div><b>{tr("agentHr.tuyen_nhan_su_ai")}</b><span>{tr("agentHr.tao_agent_tren_gateway_ghi")}</span></div>
      <button className="ui-btn is-ghost is-sm" onClick={onClose}>{tr("agentHr.dong")}</button></div>
    {!result && <ol className="hrSteps">{STEPS.map((s, i) => <li key={s} className={i === step ? "is-on" : i < step ? "is-done" : ""}>
      <span>{i + 1}</span>{s}</li>)}</ol>}
    {error && <div className="ui-banner is-error" data-testid="hr-wizard-error">{error}</div>}
    {!opt && !error && <div className="ui-empty">{tr("agentHr.dang_tai")}</div>}
    {opt && !result && <div className="ui-form">
      {step === 0 && <>
        <label>{tr("agentHr.ten")}<input value={f.name} onChange={e => set("name", e.target.value)} placeholder="VD: Thu Trang" data-testid="hr-name"/></label>
        <label>{tr("agentHr.chuc_danh")}<input value={f.role} onChange={e => set("role", e.target.value)} placeholder={tr("agentHr.vd_nhan_vien_cham_soc")} data-testid="hr-role"/></label>
        <label>{tr("agentHr.nhiem_vu_chinh_moi_dong")}<textarea rows={4} value={f.job_description} onChange={e => set("job_description", e.target.value)}
          placeholder={tr("agentHr.tra_loi_khach_tren_kenh")} data-testid="hr-job"/></label>
      </>}
      {step === 1 && <>
        <label>{tr("agentHr.phong_ban")}<select value={f.department_id} onChange={e => set("department_id", e.target.value)} data-testid="hr-dept">
          <option value="">{tr("agentHr.ban_dieu_hanh_khong_thuoc")}</option>
          {depts.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label>{tr("agentHr.nguoi_quan_ly")}<select value={f.manager_member_id} onChange={e => set("manager_member_id", e.target.value)} data-testid="hr-manager">
          <option value="">{head ? tr("agentHr.mac_dinh_truong_phong", {p0: head.name}) : tr("agentHr.chua_co_2")}</option>
          {managers.map((m: any) => <option key={m.id} value={m.id}>{m.name}{m.member_type === "agent" ? " (AI)" : ""}{m.role ? ` · ${m.role}` : ""}</option>)}</select></label>
        {dept && !head && <small className="tmGuide">{tr("agentHr.phong_nay_chua_co_truong")}</small>}
      </>}
      {step === 2 && <>
        <label>Model<select value={f.model} onChange={e => set("model", e.target.value)} data-testid="hr-model">
          {(opt.models || []).map((m: any) => <option key={m.id} value={m.id}>{m.name} ({m.id}){m.default ? tr("agentHr.mac_dinh") : ""}</option>)}
          {!opt.models?.length && <option value="">{tr("agentHr.theo_mac_dinh_cua_gateway")}</option>}</select></label>
        {opt.models_error && <small className="tmGuide">{tr("agentHr.khong_doc_duoc_models_list")} {opt.models_error}</small>}
        <label>{tr("agentHr.han_muc_chi_phi_usd")}
          <input type="number" min={0} step="1" value={f.monthly_budget} onChange={e => set("monthly_budget", e.target.value)} data-testid="hr-budget"/></label>
      </>}
      {step === 3 && <>
        <div className="hrPersona" role="radiogroup" aria-label={tr("agentHr.tinh_cach")}>{opt.personalities.map((p: any) =>
          <button key={p.key} type="button" role="radio" aria-checked={f.personality === p.key}
            className={f.personality === p.key ? "is-on" : ""} onClick={() => set("personality", p.key)} data-testid={`hr-persona-${p.key}`}>
            <b>{p.emoji} {p.label}</b><small>{p.traits[0]}</small></button>)}</div>
        <label>{tr("agentHr.dieu_nguoi_quan_ly_muon")} <small>{userLen}/3000</small>
          <textarea rows={3} value={f.manager_notes} onChange={e => set("manager_notes", e.target.value)} placeholder={tr("agentHr.bao_cao_ngan_gon_moi")} data-testid="hr-notes"/></label>
        <div className="hrSummary" data-testid="hr-summary"><b>{f.name || "—"}</b> · {f.role || tr("agentHr.nhan_su_ai")} · {dept?.name || tr("agentHr.ban_dieu_hanh")}
          {tr("agentHr.bao_cao_2")}{managers.find((m: any) => String(m.id) === String(f.manager_member_id))?.name || head?.name || tr("agentHr.ban_dieu_hanh")}
          {" · "}{f.model || tr("agentHr.model_mac_dinh")}{f.monthly_budget ? tr("agentHr.usd_thang", {p0: f.monthly_budget}) : ""}</div>
      </>}
      <div className="tmRow">
        {step > 0 && <button className="ui-btn is-ghost" onClick={() => setStep(step - 1)} disabled={busy}>{tr("agentHr.quay_lai")}</button>}
        {step < 3 && <button className="ui-btn is-primary" disabled={!canNext} onClick={() => setStep(step + 1)} data-testid="hr-next">{tr("agentHr.tiep")}</button>}
        {step === 3 && <button className="ui-btn is-primary" disabled={busy || !canNext || !f.name.trim()} onClick={submit} data-testid="hr-submit">
          {busy ? tr("agentHr.dang_tao_tren_gateway") : tr("agentHr.tuyen")}</button>}
      </div>
    </div>}
    {result && <div className="hrResult" data-testid="hr-result">
      <div className={`ui-banner ${result.status === "is-active" ? "tmNote" : "is-error"}`}>
        {result.status === "active" ? <>{tr("agentHr.da_tuyen")} <b>{f.name}</b> — agent <code>{result.runtime_agent_id}</code> {tr("agentHr.da_co_tren_gateway")}</>
          : <>{tr("agentHr.da_luu_ho_so")} <b>{f.name}</b> {tr("agentHr.nhung_gateway_chua_tao_agent")}{result.status}).</>}</div>
      <ul className="hrFiles">{result.files.map((x: any) => <li key={x.name}><span className={x.written ? "is-ok" : "is-warn"}>{x.written ? "✓" : "…"}</span>
        {x.name}{x.chars ? <small> · {x.chars} {tr("agentHr.ky_tu")}</small> : null}</li>)}</ul>
      {result.warnings?.map((w: string, i: number) => <small key={i} className="tmGuide">{w}</small>)}
      <div className="tmRow"><Link className="ui-btn is-primary" href={`/app/agents/${result.member_id}`}>{tr("agentHr.mo_ho_so")}</Link>
        <button className="ui-btn is-ghost" onClick={onClose}>{tr("agentHr.xong")}</button></div>
    </div>}
  </section>;
}

// ------------------------------------------------------------------ /app/agents/[id]

export function AgentHRPanel({memberId}: {memberId: number}) {
  const [seat, setSeat] = useState<any>(null), [all, setAll] = useState<any[]>([]), [opt, setOpt] = useState<any>(null);
  const [me, setMe] = useState<any>(null), [error, setError] = useState(""), [note, setNote] = useState<any>(null);
  const [busy, setBusy] = useState(false), [tick, setTick] = useState(0);
  useEffect(() => {
    (async () => {
      try {
        const [r, m] = await Promise.all([apiAgentsHR.roster(), apiTeam.me()]);
        setAll(r.items || []); setMe(m);
        const s = (r.items || []).find((a: any) => a.member_id === memberId);
        setSeat(s || false);
        if (s && m?.capabilities?.invite) apiAgentsHR.options().then(setOpt).catch(() => setOpt(null));
      } catch (e: any) { setError(errorText(e)); }
    })();
  }, [memberId, tick]);
  async function act(fn: () => Promise<any>, ok: (r: any) => any) {
    setBusy(true); setError(""); setNote(null);
    try { const r = await fn(); setNote(ok(r)); setTick(t => t + 1); return r; }
    catch (e: any) { setError(errorText(e)); } finally { setBusy(false); }
  }
  if (error && seat === null) return <div className="ui-banner is-error">{error}</div>;
  if (seat === null) return <div className="ui-empty">{tr("agentHr.dang_tai_nhan_su")}</div>;
  if (seat === false) return null;
  const canEdit = !!me?.capabilities?.invite && seat.lifecycle !== "retired";
  const isAdmin = ["admin", "owner"].includes(me?.role);
  return <div className="hrPanel" data-testid="hr-panel">
    {error && <div className="ui-banner is-error" data-testid="hr-error">{error}</div>}
    {note && <div className="ui-banner tmNote" data-testid="hr-note">{note}</div>}
    <div className="ui-grid is-2">
      <HrForm seat={seat} opt={opt} canEdit={canEdit} busy={busy} act={act}/>
      <Lifecycle seat={seat} all={all} canEdit={!!me?.capabilities?.invite} busy={busy} act={act}/>
    </div>
    <Drift seat={seat} canEdit={canEdit} busy={busy} act={act} tick={tick}/>
    <Tools seat={seat} isAdmin={isAdmin} busy={busy} act={act} tick={tick}/>
  </div>;
}

function HrForm({seat, opt, canEdit, busy, act}: any) {
  const [f, setF] = useState<any>({});
  useEffect(() => setF({name: seat.name, role: seat.role, department_id: seat.department_id ?? "",
    manager_member_id: seat.manager_id ?? "", model: seat.model || ""}), [seat]);
  const set = (k: string, v: any) => setF((x: any) => ({...x, [k]: v}));
  const depts = (opt?.departments || []).filter((d: any) => d.company_id === seat.company_id);
  const managers = (opt?.managers || []).filter((m: any) => m.company_id === seat.company_id && m.id !== seat.member_id);
  const [persona, setPersona] = useState("");
  function body() {
    const b: any = {};
    if (f.name !== seat.name) b.name = f.name;
    if (f.role !== seat.role) b.role = f.role;
    if (String(f.department_id) !== String(seat.department_id ?? "")) b.department_id = f.department_id ? Number(f.department_id) : null;
    if (String(f.manager_member_id) !== String(seat.manager_id ?? "")) b.manager_member_id = f.manager_member_id ? Number(f.manager_member_id) : null;
    if (f.model && f.model !== seat.model) b.model = f.model;
    if (persona) b.personality = persona;
    return b;
  }
  const changes = Object.keys(body());
  const report = (r: any) => <span>
    {r.changed?.length ? <>{tr("agentHr.da_luu")} {r.changed.join(", ")}.</> : tr("agentHr.khong_co_gi_doi")}
    {Object.entries(r.files || {}).map(([k, v]: any) => <span key={k}> {k}: {v.written ? tr("agentHr.da_ghi_len_gateway") : v.reason === "customized" ? tr("agentHr.giu_ban_da_chinh_tay") : v.reason === "edited_on_gateway" ? tr("agentHr.dang_lech_khong_ghi_de") : v.reason === "unchanged" ? tr("agentHr.khong_doi") : v.message || v.reason}.</span>)}
    {r.warnings?.map((w: string, i: number) => <span key={i} className="hrWarn"> {w}</span>)}
    {Object.values(r.files || {}).some((v: any) => v.reason === "customized") &&
      <> <button className="ui-btn is-ghost is-sm" onClick={() => act(() => apiAgentsHR.update(seat.agent_id, {regenerate_files:
        Object.entries(r.files).filter(([, v]: any) => v.reason === "customized").map(([k]) => k)}), report)} data-testid="hr-regen">{tr("agentHr.sinh_lai_tu_ho_so")}</button></>}
  </span>;
  return <section className="ui-panel ui-panel-body" data-testid="hr-form">
    <div className="lab-cardhead"><div><b>{tr("agentHr.ho_so_nhan_su")}</b><span>{tr("agentHr.luu_ghi_database_gateway_agents")}</span></div></div>
    <div className="ui-form">
      <div className="ui-form-row">
        <label>{tr("agentHr.ten")}<input value={f.name || ""} disabled={!canEdit} onChange={e => set("name", e.target.value)} data-testid="hr-edit-name"/></label>
        <label>{tr("agentHr.chuc_danh")}<input value={f.role || ""} disabled={!canEdit} onChange={e => set("role", e.target.value)} data-testid="hr-edit-role"/></label>
      </div>
      <div className="ui-form-row">
        <label>{tr("agentHr.phong_ban")}<select value={f.department_id} disabled={!canEdit || !opt} onChange={e => set("department_id", e.target.value)}>
          <option value="">{tr("agentHr.ban_dieu_hanh")}</option>
          {depts.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
          {!opt && seat.department_id && <option value={seat.department_id}>{seat.department}</option>}</select></label>
        <label>{tr("agentHr.bao_cao_cho")}<select value={f.manager_member_id} disabled={!canEdit || !opt} onChange={e => set("manager_member_id", e.target.value)}>
          <option value="">—</option>
          {managers.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}
          {!opt && seat.manager_id && <option value={seat.manager_id}>{seat.manager}</option>}</select></label>
      </div>
      <div className="ui-form-row">
        <label>Model<select value={f.model} disabled={!canEdit || !opt} onChange={e => set("model", e.target.value)} data-testid="hr-edit-model">
          {!(opt?.models || []).some((m: any) => m.id === f.model) && <option value={f.model}>{f.model || "—"}</option>}
          {(opt?.models || []).map((m: any) => <option key={m.id} value={m.id}>{m.id}</option>)}</select></label>
        <label>{tr("agentHr.tinh_cach_sinh_lai_soul")}<select value={persona} disabled={!canEdit || !opt} onChange={e => setPersona(e.target.value)} data-testid="hr-edit-persona">
          <option value="">{tr("agentHr.giu_nguyen")}</option>
          {(opt?.personalities || []).map((p: any) => <option key={p.key} value={p.key}>{p.emoji} {p.label}</option>)}</select></label>
      </div>
      {canEdit ? <button className="ui-btn is-primary" disabled={busy || !changes.length} data-testid="hr-save"
        onClick={() => act(() => apiAgentsHR.update(seat.agent_id, body()), report).then(() => setPersona(""))}>{tr("agentHr.luu")}{changes.length ? ` (${changes.length})` : ""}</button>
        : <small className="tmGuide">{seat.lifecycle === "retired" ? tr("agentHr.nhan_su_da_nghi_ho") : tr("agentHr.can_vai_quan_ly_tro")}</small>}
    </div>
  </section>;
}

function Lifecycle({seat, all, canEdit, busy, act}: any) {
  const [retire, setRetire] = useState(false), [to, setTo] = useState(""), [keep, setKeep] = useState(false), [reason, setReason] = useState("");
  const others = all.filter((a: any) => a.company_id === seat.company_id && a.agent_id !== seat.agent_id && a.lifecycle === "active");
  const lc = seat.lifecycle;
  const said = (r: any) => {
    if (r.action === "retire") {
      const g = r.gateway || {};
      return <span data-testid="hr-retire-result">{tr("agentHr.da_cho_nghi_phien_tren")} {g.sessions_before ?? "?"} → <b>{g.sessions_after ?? "?"}</b>
        {g.agent_removed ? tr("agentHr.da_go_agent_khoi_gateway") : ""}. {r.tasks_reassigned?.count || 0} {tr("agentHr.viec_chuyen_cho")} {r.tasks_reassigned?.to}.
        {r.reports_moved ? tr("agentHr.nguoi_bao_cao_chuyen_len", {p0: r.reports_moved}) : ""}
        {g.files_archived?.length ? tr("agentHr.da_luu_file_ho_so", {p0: g.files_archived.length}) : ""}
        {r.warnings?.map((w: string, i: number) => <span key={i} className="hrWarn"> {w}</span>)}</span>;
    }
    return <span>{r.action === "pause" ? tr("agentHr.da_tam_dung_agent_khong", {p0: r.aborted?.tasks?.length ? `, dừng ${r.aborted.tasks.length} việc đang chạy` : ""})
      : tr("agentHr.da_cho_lam_tiep", {p0: LIFECYCLE_VI[r.lifecycle] || r.lifecycle})}{r.warnings?.map((w: string, i: number) => <span key={i} className="hrWarn"> {w}</span>)}</span>;
  };
  return <section className="ui-panel ui-panel-body" data-testid="hr-lifecycle-card">
    <div className="lab-cardhead"><div><b>{tr("agentHr.vong_doi")}</b><span>{tr("agentHr.tam_dung_chan_luot_moi")}</span></div><Pill lc={lc}/></div>
    <dl className="hrFacts"><dt>Agent</dt><dd><code>{seat.runtime_agent_id}</code></dd>
      <dt>{tr("agentHr.tren_gateway")}</dt><dd>{seat.on_gateway === null ? tr("agentHr.khong_doc_duoc") : seat.on_gateway ? tr("agentHr.co_phien", {p0: seat.sessions, p1: seat.running ? tr("agentHr.dang_chay_hau_to") : ""}) : tr("agentHr.khong_co")}</dd></dl>
    {canEdit && lc !== "retired" && <div className="tmRow">
      {lc === "paused" ? <button className="ui-btn is-primary" disabled={busy} data-testid="hr-resume"
          onClick={() => act(() => apiAgentsHR.lifecycle(seat.agent_id, {action: "resume"}), said)}>{tr("agentHr.tiep_tuc")}</button>
        : <button className="ui-btn is-sm" disabled={busy} data-testid="hr-pause"
          onClick={() => act(() => apiAgentsHR.lifecycle(seat.agent_id, {action: "pause"}), said)}>{tr("agentHr.tam_dung_nut")}</button>}
      <button className="ui-btn is-sm is-danger" disabled={busy} onClick={() => setRetire(!retire)} data-testid="hr-retire-open">{tr("agentHr.cho_nghi_viec")}</button>
    </div>}
    {retire && lc !== "retired" && <div className="hrConfirm ui-form" data-testid="hr-retire-confirm">
      <b>{tr("agentHr.cho_nghi_viec_ten", {p0: seat.name})}</b>
      <small>{tr("agentHr.dung_viec_dang_chay_xoa")}</small>
      <label>{tr("agentHr.viec_dang_mo_giao_cho")}<select value={to} onChange={e => setTo(e.target.value)} data-testid="hr-retire-to">
        <option value="">{tr("agentHr.tra_ve_phong_ban_truong")}</option>
        {others.map((a: any) => <option key={a.member_id} value={a.member_id}>{a.name}</option>)}</select></label>
      <label className="hrCheck"><input type="checkbox" checked={keep} onChange={e => setKeep(e.target.checked)}/> {tr("agentHr.giu_agent_tren_gateway_chi")}</label>
      <label>{tr("agentHr.ly_do")}<input value={reason} onChange={e => setReason(e.target.value)} placeholder={tr("agentHr.vd_het_du_an")}/></label>
      <div className="tmRow"><button className="ui-btn is-primary hrDangerFill" disabled={busy} data-testid="hr-retire"
        onClick={() => act(() => apiAgentsHR.lifecycle(seat.agent_id, {action: "retire", reassign_to_member_id: to ? Number(to) : null,
          remove_from_gateway: !keep, reason}), said).then(() => setRetire(false))}>{tr("agentHr.xac_nhan_cho_nghi")}</button>
        <button className="ui-btn is-ghost" onClick={() => setRetire(false)}>{tr("agentHr.huy")}</button></div>
    </div>}
  </section>;
}

function Drift({seat, canEdit, busy, act, tick}: any) {
  const [d, setD] = useState<any>(null), [err, setErr] = useState(""), [open, setOpen] = useState<string>("");
  async function load() { setErr(""); try { setD(await apiAgentsHR.drift(seat.agent_id)); } catch (e: any) { setErr(errorText(e)); } }
  useEffect(() => { load(); }, [seat.agent_id, tick]);
  const sync = (direction: "push" | "pull", files?: string[], fields?: string[]) =>
    act(() => apiAgentsHR.resync(seat.agent_id, {direction, files, fields}), (r: any) => {
      setD(r.drift);
      const ok = r.done.filter((x: any) => x.ok).length, bad = r.done.filter((x: any) => !x.ok);
      return <span>{direction === "push" ? tr("agentHr.da_day_ban_clawcompany_len") : tr("agentHr.da_nhan_ban_gateway")}: {ok} {tr("agentHr.muc")}{bad.length ? tr("agentHr.loi", {p0: bad.map((x: any) => `${x.file || x.field} (${x.reason})`).join(", ")}) : ""}.</span>;
    });
  const drifted = (d?.files || []).filter((f: any) => f.counts_as_drift);
  const fieldsBad = (d?.fields || []).filter((f: any) => !f.match);
  return <section className="ui-panel ui-panel-body" data-testid="hr-drift">
    <div className="lab-cardhead"><div><b>{tr("agentHr.dong_bo_voi_gateway")}</b>
      <span>{!d ? tr("agentHr.dang_kiem") : d.in_sync ? tr("agentHr.khop_ban_clawcompany_va_gateway") : tr("agentHr.lech_muc", {p0: d.drift_count})}</span></div>
      <div className="tmRow"><button className="ui-btn is-ghost is-sm" onClick={load} disabled={busy}>{tr("agentHr.kiem_tra_lai")}</button>
        {canEdit && d && (!d.roster_match || (d.files || []).some((f: any) => f.status === "untracked" && f.counts_as_drift)) &&
          <button className="ui-btn is-primary is-sm" disabled={busy} data-testid="hr-provision"
            onClick={() => act(() => apiAgentsHR.provision(seat.agent_id), (r: any) => {
              load();
              const n = (r.steps?.find((x: any) => x.step === "files")?.written || []).length;
              return <span>{tr("agentHr.da_hoan_thien_tren_gateway", {p0: n})}{r.warnings?.length ? " · " + r.warnings.join("; ") : ""}</span>;
            })}>{tr("agentHr.tao_hoan_thien_tren_gateway")}</button>}
        {canEdit && d && !d.in_sync && d.roster_match && <>
          <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => sync("push")} data-testid="hr-push-all">{tr("agentHr.dong_bo_lai_day_len")}</button>
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("pull")} data-testid="hr-pull-all">{tr("agentHr.nhan_ban_gateway")}</button></>}</div></div>
    {err && <div className="ui-banner is-error">{err}</div>}
    {d?.warnings?.map((w: string, i: number) => <small key={i} className="tmGuide">{w}</small>)}
    {d && <table className="ui-table"><tbody>
      {(d.fields || []).map((f: any) => <tr key={f.field} className={f.match ? "" : "is-err"}>
        <td><b>{f.label}</b></td><td><small>ClawCompany: {f.clawcompany || "—"}<br/>Gateway: {f.gateway || "—"}</small></td>
        <td>{f.match ? tr("agentHr.khop") : <span className="is-warn">{tr("agentHr.lech")}</span>}</td>
        <td style={{textAlign: "right"}}>{!f.match && canEdit && <span className="tmRow">
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("push", [], [f.field])}>{tr("agentHr.day_len")}</button>
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("pull", [], [f.field])}>{tr("agentHr.nhan_ve")}</button></span>}</td></tr>)}
      {(d.files || []).map((f: any) => <tr key={f.name} className={f.counts_as_drift ? "is-err" : ""} data-testid={`hr-file-${f.name}`}>
        <td><b>{f.name}</b>{f.agent_owned && <><br/><small>{tr("agentHr.agent_tu_ghi")}</small></>}</td>
        <td><small>{FILE_VI[f.status] || f.status}{f.clawcompany_source === "gateway_accepted" ? tr("agentHr.ban_da_nhan_tu_gateway") : ""}</small>
          {f.status === "edited_on_gateway" && <><br/><button className="hrLinkBtn" onClick={() => setOpen(open === f.name ? "" : f.name)}>{open === f.name ? tr("agentHr.an_so_sanh") : tr("agentHr.xem_khac_biet")}</button></>}</td>
        <td>{f.status === "in_sync" ? tr("agentHr.khop") : f.counts_as_drift ? <span className="is-warn">{tr("agentHr.lech")}</span> : <small>—</small>}</td>
        <td style={{textAlign: "right"}}>{canEdit && ["edited_on_gateway", "missing_on_gateway", "untracked"].includes(f.status) && <span className="tmRow">
          {f.status !== "untracked" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("push", [f.name], [])}>{tr("agentHr.day_len")}</button>}
          {f.status !== "missing_on_gateway" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("pull", [f.name], [])}>{tr("agentHr.nhan_ve")}</button>}</span>}</td></tr>)}
    </tbody></table>}
    {open && (() => { const f = d.files.find((x: any) => x.name === open); return f ? <DiffView a={f.clawcompany_content || ""} b={f.gateway_content || ""}/> : null; })()}
    {d && drifted.length === 0 && fieldsBad.length === 0 && d.roster_match && <small className="tmGuide">{tr("agentHr.sua_tay_tren_may_gateway")}</small>}
  </section>;
}

function DiffView({a, b}: {a: string; b: string}) {
  const rows = useMemo(() => {
    const A = a.split("\n"), B = b.split("\n"), setA = new Set(A), setB = new Set(B);
    return {left: A.map(l => ({l, gone: !setB.has(l)})), right: B.map(l => ({l, added: !setA.has(l)}))};
  }, [a, b]);
  return <div className="hrDiff" data-testid="hr-diff">
    <div><b>{tr("agentHr.ban_clawcompany")}</b><pre>{rows.left.map((r, i) => <span key={i} className={r.gone ? "is-gone" : ""}>{r.l || " "}</span>)}</pre></div>
    <div><b>{tr("agentHr.ban_tren_gateway")}</b><pre>{rows.right.map((r, i) => <span key={i} className={r.added ? "is-added" : ""}>{r.l || " "}</span>)}</pre></div>
  </div>;
}

function Tools({seat, isAdmin, busy, act, tick}: any) {
  const [t, setT] = useState<any>(null), [err, setErr] = useState("");
  useEffect(() => { apiAgentsHR.tools(seat.agent_id).then(setT).catch(e => setErr(errorText(e))); }, [seat.agent_id, tick]);
  const src = (s: string) => s === "member" ? tr("agentHr.rieng_ghe_nay") : s.startsWith("tier") ? tr("agentHr.theo_bac") : s.startsWith("default") ? tr("agentHr.mac_dinh_2") : s;
  return <section className="ui-panel ui-panel-body" data-testid="hr-tools">
    <div className="lab-cardhead"><div><b>{tr("agentHr.quyen_dung_tool_cong_ty")}</b>
      <span>{t ? tr("agentHr.bac_ghe_dat_rieng_cho", {p0: t.tier_label}) : tr("agentHr.dang_tai")}</span></div>
      <Link className="ui-btn" href="/app/agent-tools">{tr("agentHr.ma_tran_theo_bac")}</Link></div>
    {err && <div className="ui-banner is-error">{err}</div>}
    {t && <div className="hrScroll"><table className="ui-table"><tbody>{t.tools.map((x: any) => <tr key={x.name}>
      <td><b>{x.name}</b><br/><small>{x.description}</small></td>
      <td><small>{x.group}{x.writes ? tr("agentHr.ghi_hau_to") : ""}</small></td>
      <td>{isAdmin && seat.lifecycle !== "retired" ? <select value={x.source === "member" ? x.level : "inherit"} disabled={busy} data-testid={`hr-tool-${x.name}`}
          onChange={e => act(() => apiMcp.setPermission({tool: x.name, level: e.target.value, member_id: seat.member_id}),
            () => tr("agentHr.da_dat", {p0: x.name, p1: e.target.value === "inherit" ? tr("agentHr.theo_bac") : LEVEL_VI[e.target.value]}))}>
          <option value="inherit">{x.source === "member" ? tr("agentHr.theo_bac_mac_dinh") : tr("agentHr.theo_bac_mac_dinh_2", {p0: LEVEL_VI[x.level] || x.level})}</option>
          {t.levels.map((l: string) => <option key={l} value={l}>{LEVEL_VI[l] || l}</option>)}</select>
        : <span className={x.level === "off" ? "is-warn" : ""}>{LEVEL_VI[x.level] || x.level}</span>}</td>
      <td className="hrSrc"><small>{src(x.source)}</small></td></tr>)}</tbody></table></div>}
    {t && !isAdmin && <small className="tmGuide">{tr("agentHr.doi_quyen_tool_can_vai")}</small>}
  </section>;
}
