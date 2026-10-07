"use client";
// M3 — Nhân sự AI: danh sách đối chiếu gateway + wizard tuyển 4 bước (tab "Nhân sự AI"
// của /app/team), và bảng điều khiển trên /app/agents/[id]: sửa hồ sơ ghi 2 chiều,
// vòng đời (tạm dừng / tiếp tục / cho nghỉ), lệch & "Đồng bộ lại", quyền tool theo seat.
import {useEffect, useMemo, useState} from "react";
import Link from "next/link";
import {apiAgentsHR, apiMcp, apiTeam, errorText} from "../lib/api";

export const LIFECYCLE_VI: Record<string, string> = {
  active: "Đang làm", paused: "Tạm dừng", retired: "Đã nghỉ", runtime_missing: "Chờ gateway",
  provisioning: "Đang tạo", runtime_error: "Lỗi tạo", detached: "Mất trên gateway",
};
const LIFECYCLE_CLS: Record<string, string> = {active: "", paused: "busy", retired: "off", runtime_missing: "busy",
  runtime_error: "busy", detached: "busy", provisioning: "busy"};
const FILE_VI: Record<string, string> = {in_sync: "Khớp", edited_on_gateway: "Bị sửa trên gateway",
  missing_on_gateway: "Mất trên gateway", untracked: "Chưa có bản ClawCompany", absent: "Chưa có", no_agent: "Không có agent", error: "Lỗi đọc"};
const LEVEL_VI: Record<string, string> = {allowed: "Cho phép", ask: "Hỏi duyệt", off: "Tắt"};

function Pill({lc}: {lc: string}) {
  return <span className={`statusPill ${LIFECYCLE_CLS[lc] ?? "busy"}`} data-testid="hr-lifecycle">{LIFECYCLE_VI[lc] || lc}</span>;
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
  if (!roster) return <div className="ui-empty">Đang tải…</div>;
  const c = roster.counts || {};
  return <div className="hrWrap">
    <section className="v8Card">
      <div className="v8CardHead"><div><b>Nhân sự AI</b>
        <span>{roster.items.length} agent · {c.active || 0} đang làm{c.paused ? ` · ${c.paused} tạm dừng` : ""}{c.retired ? ` · ${c.retired} đã nghỉ` : ""}{c.runtime_missing ? ` · ${c.runtime_missing} chờ gateway` : ""}</span></div>
        {caps.invite && <button className="ui-btn is-primary" onClick={() => setWizard(true)} data-testid="hr-hire-open">Tuyển nhân sự AI</button>}
      </div>
      {roster.gateway_error && <div className="ui-banner is-error">Không đọc được gateway: {roster.gateway_error}</div>}
      {roster.unbound_on_gateway > 0 && <small className="tmGuide">{roster.unbound_on_gateway} agent trên gateway chưa gắn vào ghế nào.</small>}
      <div className="hrScroll"><table className="tmTable" data-testid="hr-roster"><thead><tr>
        <th>Tên</th><th>Phòng ban · quản lý</th><th>Model</th><th>Trạng thái</th><th>Gateway</th></tr></thead>
        <tbody>{roster.items.map((a: any) => <tr key={a.agent_id} className={a.lifecycle === "retired" ? "is-off" : ""}>
          <td><Link href={`/app/agents/${a.member_id}`}><b>{a.name}</b></Link><br/><small>{a.role}{a.is_head ? " · Trưởng phòng" : ""}</small></td>
          <td><small>{a.department || "Ban điều hành"}<br/>{a.manager ? `báo cáo ${a.manager}` : "—"}</small></td>
          <td><small>{a.model || a.gateway_model || "—"}</small></td>
          <td><Pill lc={a.lifecycle}/></td>
          <td><small>{a.on_gateway === null ? "?" : a.on_gateway ? `có · ${a.sessions} phiên${a.running ? " · đang chạy" : ""}` : a.lifecycle === "retired" ? "đã gỡ" : <span className="is-warn">không có</span>}</small></td>
        </tr>)}</tbody></table></div>
      {!roster.items.length && <div className="ui-empty">Chưa có nhân sự AI nào{caps.invite ? " — bấm “Tuyển nhân sự AI”." : "."}</div>}
    </section>
    {wizard && <HireWizard companyId={companyId} onClose={() => setWizard(false)} onDone={load}/>}
  </div>;
}

const STEPS = ["Vai trò", "Phòng ban", "Model & ngân sách", "Tính cách"];

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
  return <section className="v8Card hrWizard" data-testid="hr-wizard">
    <div className="v8CardHead"><div><b>Tuyển nhân sự AI</b><span>Tạo agent trên gateway + ghi đủ 5 file hồ sơ (IDENTITY, SOUL, AGENTS, USER, MEMORY)</span></div>
      <button className="ui-btn is-ghost is-sm" onClick={onClose}>Đóng</button></div>
    {!result && <ol className="hrSteps">{STEPS.map((s, i) => <li key={s} className={i === step ? "is-on" : i < step ? "is-done" : ""}>
      <span>{i + 1}</span>{s}</li>)}</ol>}
    {error && <div className="ui-banner is-error" data-testid="hr-wizard-error">{error}</div>}
    {!opt && !error && <div className="ui-empty">Đang tải…</div>}
    {opt && !result && <div className="v9Form">
      {step === 0 && <>
        <label>Tên<input value={f.name} onChange={e => set("name", e.target.value)} placeholder="VD: Thu Trang" data-testid="hr-name"/></label>
        <label>Chức danh<input value={f.role} onChange={e => set("role", e.target.value)} placeholder="VD: Nhân viên chăm sóc khách hàng" data-testid="hr-role"/></label>
        <label>Nhiệm vụ chính (mỗi dòng một việc)<textarea rows={4} value={f.job_description} onChange={e => set("job_description", e.target.value)}
          placeholder={"Trả lời khách trên kênh chat\nTổng hợp phản hồi hằng tuần"} data-testid="hr-job"/></label>
      </>}
      {step === 1 && <>
        <label>Phòng ban<select value={f.department_id} onChange={e => set("department_id", e.target.value)} data-testid="hr-dept">
          <option value="">— Ban điều hành (không thuộc phòng) —</option>
          {depts.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label>Người quản lý<select value={f.manager_member_id} onChange={e => set("manager_member_id", e.target.value)} data-testid="hr-manager">
          <option value="">{head ? `Mặc định: trưởng phòng ${head.name}` : "— chưa có —"}</option>
          {managers.map((m: any) => <option key={m.id} value={m.id}>{m.name}{m.member_type === "agent" ? " (AI)" : ""}{m.role ? ` · ${m.role}` : ""}</option>)}</select></label>
        {dept && !head && <small className="tmGuide">Phòng này chưa có trưởng phòng — đặt ở tab “Phòng ban”.</small>}
      </>}
      {step === 2 && <>
        <label>Model<select value={f.model} onChange={e => set("model", e.target.value)} data-testid="hr-model">
          {(opt.models || []).map((m: any) => <option key={m.id} value={m.id}>{m.name} ({m.id}){m.default ? " · mặc định" : ""}</option>)}
          {!opt.models?.length && <option value="">Theo mặc định của gateway</option>}</select></label>
        {opt.models_error && <small className="tmGuide">Không đọc được models.list: {opt.models_error}</small>}
        <label>Hạn mức chi phí (USD/tháng, để trống = theo ngân sách phòng/công ty)
          <input type="number" min={0} step="1" value={f.monthly_budget} onChange={e => set("monthly_budget", e.target.value)} data-testid="hr-budget"/></label>
      </>}
      {step === 3 && <>
        <div className="hrPersona" role="radiogroup" aria-label="Tính cách">{opt.personalities.map((p: any) =>
          <button key={p.key} type="button" role="radio" aria-checked={f.personality === p.key}
            className={f.personality === p.key ? "is-on" : ""} onClick={() => set("personality", p.key)} data-testid={`hr-persona-${p.key}`}>
            <b>{p.emoji} {p.label}</b><small>{p.traits[0]}</small></button>)}</div>
        <label>Điều người quản lý muốn (USER.md) <small>{userLen}/3000</small>
          <textarea rows={3} value={f.manager_notes} onChange={e => set("manager_notes", e.target.value)} placeholder="- Báo cáo ngắn gọn mỗi sáng thứ Hai" data-testid="hr-notes"/></label>
        <div className="hrSummary" data-testid="hr-summary"><b>{f.name || "—"}</b> · {f.role || "Nhân sự AI"} · {dept?.name || "Ban điều hành"}
          {" · báo cáo "}{managers.find((m: any) => String(m.id) === String(f.manager_member_id))?.name || head?.name || "Ban điều hành"}
          {" · "}{f.model || "model mặc định"}{f.monthly_budget ? ` · ${f.monthly_budget} USD/tháng` : ""}</div>
      </>}
      <div className="tmRow">
        {step > 0 && <button className="ui-btn is-ghost" onClick={() => setStep(step - 1)} disabled={busy}>Quay lại</button>}
        {step < 3 && <button className="ui-btn is-primary" disabled={!canNext} onClick={() => setStep(step + 1)} data-testid="hr-next">Tiếp</button>}
        {step === 3 && <button className="ui-btn is-primary" disabled={busy || !canNext || !f.name.trim()} onClick={submit} data-testid="hr-submit">
          {busy ? "Đang tạo trên gateway…" : "Tuyển"}</button>}
      </div>
    </div>}
    {result && <div className="hrResult" data-testid="hr-result">
      <div className={`ui-banner ${result.status === "active" ? "tmNote" : "is-error"}`}>
        {result.status === "active" ? <>Đã tuyển <b>{f.name}</b> — agent <code>{result.runtime_agent_id}</code> đã có trên gateway.</>
          : <>Đã lưu hồ sơ <b>{f.name}</b> nhưng gateway chưa tạo agent ({result.status}).</>}</div>
      <ul className="hrFiles">{result.files.map((x: any) => <li key={x.name}><span className={x.written ? "is-ok" : "is-warn"}>{x.written ? "✓" : "…"}</span>
        {x.name}{x.chars ? <small> · {x.chars} ký tự</small> : null}</li>)}</ul>
      {result.warnings?.map((w: string, i: number) => <small key={i} className="tmGuide">{w}</small>)}
      <div className="tmRow"><Link className="ui-btn is-primary" href={`/app/agents/${result.member_id}`}>Mở hồ sơ</Link>
        <button className="ui-btn is-ghost" onClick={onClose}>Xong</button></div>
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
  if (seat === null) return <div className="ui-empty">Đang tải nhân sự…</div>;
  if (seat === false) return null;
  const canEdit = !!me?.capabilities?.invite && seat.lifecycle !== "retired";
  const isAdmin = ["admin", "owner"].includes(me?.role);
  return <div className="hrPanel" data-testid="hr-panel">
    {error && <div className="ui-banner is-error" data-testid="hr-error">{error}</div>}
    {note && <div className="ui-banner tmNote" data-testid="hr-note">{note}</div>}
    <div className="v9Grid2">
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
    {r.changed?.length ? <>Đã lưu: {r.changed.join(", ")}.</> : "Không có gì đổi."}
    {Object.entries(r.files || {}).map(([k, v]: any) => <span key={k}> {k}: {v.written ? "đã ghi lên gateway" : v.reason === "customized" ? "giữ bản đã chỉnh tay" : v.reason === "edited_on_gateway" ? "đang lệch — không ghi đè" : v.reason === "unchanged" ? "không đổi" : v.message || v.reason}.</span>)}
    {r.warnings?.map((w: string, i: number) => <span key={i} className="hrWarn"> {w}</span>)}
    {Object.values(r.files || {}).some((v: any) => v.reason === "customized") &&
      <> <button className="ui-btn is-ghost is-sm" onClick={() => act(() => apiAgentsHR.update(seat.agent_id, {regenerate_files:
        Object.entries(r.files).filter(([, v]: any) => v.reason === "customized").map(([k]) => k)}), report)} data-testid="hr-regen">Sinh lại từ hồ sơ</button></>}
  </span>;
  return <section className="v8Card" data-testid="hr-form">
    <div className="v8CardHead"><div><b>Hồ sơ nhân sự</b><span>Lưu = ghi database + gateway (agents.update, IDENTITY/SOUL/AGENTS/USER)</span></div></div>
    <div className="v9Form">
      <div className="v9FormRow">
        <label>Tên<input value={f.name || ""} disabled={!canEdit} onChange={e => set("name", e.target.value)} data-testid="hr-edit-name"/></label>
        <label>Chức danh<input value={f.role || ""} disabled={!canEdit} onChange={e => set("role", e.target.value)} data-testid="hr-edit-role"/></label>
      </div>
      <div className="v9FormRow">
        <label>Phòng ban<select value={f.department_id} disabled={!canEdit || !opt} onChange={e => set("department_id", e.target.value)}>
          <option value="">Ban điều hành</option>
          {depts.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
          {!opt && seat.department_id && <option value={seat.department_id}>{seat.department}</option>}</select></label>
        <label>Báo cáo cho<select value={f.manager_member_id} disabled={!canEdit || !opt} onChange={e => set("manager_member_id", e.target.value)}>
          <option value="">—</option>
          {managers.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}
          {!opt && seat.manager_id && <option value={seat.manager_id}>{seat.manager}</option>}</select></label>
      </div>
      <div className="v9FormRow">
        <label>Model<select value={f.model} disabled={!canEdit || !opt} onChange={e => set("model", e.target.value)} data-testid="hr-edit-model">
          {!(opt?.models || []).some((m: any) => m.id === f.model) && <option value={f.model}>{f.model || "—"}</option>}
          {(opt?.models || []).map((m: any) => <option key={m.id} value={m.id}>{m.id}</option>)}</select></label>
        <label>Tính cách (sinh lại SOUL)<select value={persona} disabled={!canEdit || !opt} onChange={e => setPersona(e.target.value)} data-testid="hr-edit-persona">
          <option value="">— giữ nguyên —</option>
          {(opt?.personalities || []).map((p: any) => <option key={p.key} value={p.key}>{p.emoji} {p.label}</option>)}</select></label>
      </div>
      {canEdit ? <button className="ui-btn is-primary" disabled={busy || !changes.length} data-testid="hr-save"
        onClick={() => act(() => apiAgentsHR.update(seat.agent_id, body()), report).then(() => setPersona(""))}>Lưu{changes.length ? ` (${changes.length})` : ""}</button>
        : <small className="tmGuide">{seat.lifecycle === "retired" ? "Nhân sự đã nghỉ — hồ sơ chỉ để xem." : "Cần vai Quản lý trở lên để sửa."}</small>}
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
      return <span data-testid="hr-retire-result">Đã cho nghỉ. Phiên trên gateway: {g.sessions_before ?? "?"} → <b>{g.sessions_after ?? "?"}</b>
        {g.agent_removed ? "; đã gỡ agent khỏi gateway" : ""}. {r.tasks_reassigned?.count || 0} việc chuyển cho {r.tasks_reassigned?.to}.
        {r.reports_moved ? ` ${r.reports_moved} người báo cáo chuyển lên quản lý trên.` : ""}
        {g.files_archived?.length ? ` Đã lưu ${g.files_archived.length} file hồ sơ.` : ""}
        {r.warnings?.map((w: string, i: number) => <span key={i} className="hrWarn"> {w}</span>)}</span>;
    }
    return <span>{r.action === "pause" ? `Đã tạm dừng${r.aborted?.tasks?.length ? `, dừng ${r.aborted.tasks.length} việc đang chạy` : ""}. Agent không nhận lượt mới.`
      : `Đã cho làm tiếp (${LIFECYCLE_VI[r.lifecycle] || r.lifecycle}).`}{r.warnings?.map((w: string, i: number) => <span key={i} className="hrWarn"> {w}</span>)}</span>;
  };
  return <section className="v8Card" data-testid="hr-lifecycle-card">
    <div className="v8CardHead"><div><b>Vòng đời</b><span>Tạm dừng chặn lượt mới; cho nghỉ dọn sạch phiên trên gateway</span></div><Pill lc={lc}/></div>
    <dl className="hrFacts"><dt>Agent</dt><dd><code>{seat.runtime_agent_id}</code></dd>
      <dt>Trên gateway</dt><dd>{seat.on_gateway === null ? "không đọc được" : seat.on_gateway ? `có · ${seat.sessions} phiên${seat.running ? " · đang chạy" : ""}` : "không có"}</dd></dl>
    {canEdit && lc !== "retired" && <div className="tmRow">
      {lc === "paused" ? <button className="ui-btn is-primary" disabled={busy} data-testid="hr-resume"
          onClick={() => act(() => apiAgentsHR.lifecycle(seat.agent_id, {action: "resume"}), said)}>Tiếp tục</button>
        : <button className="ui-btn is-ghost" disabled={busy} data-testid="hr-pause"
          onClick={() => act(() => apiAgentsHR.lifecycle(seat.agent_id, {action: "pause"}), said)}>Tạm dừng</button>}
      <button className="ui-btn is-ghost hrDanger" disabled={busy} onClick={() => setRetire(!retire)} data-testid="hr-retire-open">Cho nghỉ việc…</button>
    </div>}
    {retire && lc !== "retired" && <div className="hrConfirm v9Form" data-testid="hr-retire-confirm">
      <b>Cho {seat.name} nghỉ việc?</b>
      <small>Dừng việc đang chạy, xoá mọi phiên trên gateway, bỏ chức trưởng phòng, chuyển người báo cáo lên quản lý trên, khoá API key. Không hoàn tác — muốn quay lại phải tuyển mới (hồ sơ 5 file được lưu).</small>
      <label>Việc đang mở giao cho<select value={to} onChange={e => setTo(e.target.value)} data-testid="hr-retire-to">
        <option value="">Trả về phòng ban (trưởng phòng giao lại)</option>
        {others.map((a: any) => <option key={a.member_id} value={a.member_id}>{a.name}</option>)}</select></label>
      <label className="hrCheck"><input type="checkbox" checked={keep} onChange={e => setKeep(e.target.checked)}/> Giữ agent trên gateway (chỉ xoá phiên, đặt lại phiên chính)</label>
      <label>Lý do<input value={reason} onChange={e => setReason(e.target.value)} placeholder="VD: hết dự án"/></label>
      <div className="tmRow"><button className="ui-btn is-primary hrDangerFill" disabled={busy} data-testid="hr-retire"
        onClick={() => act(() => apiAgentsHR.lifecycle(seat.agent_id, {action: "retire", reassign_to_member_id: to ? Number(to) : null,
          remove_from_gateway: !keep, reason}), said).then(() => setRetire(false))}>Xác nhận cho nghỉ</button>
        <button className="ui-btn is-ghost" onClick={() => setRetire(false)}>Huỷ</button></div>
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
      return <span>{direction === "push" ? "Đã đẩy bản ClawCompany lên gateway" : "Đã nhận bản gateway"}: {ok} mục{bad.length ? `; lỗi: ${bad.map((x: any) => `${x.file || x.field} (${x.reason})`).join(", ")}` : ""}.</span>;
    });
  const drifted = (d?.files || []).filter((f: any) => f.counts_as_drift);
  const fieldsBad = (d?.fields || []).filter((f: any) => !f.match);
  return <section className="v8Card" data-testid="hr-drift">
    <div className="v8CardHead"><div><b>Đồng bộ với gateway</b>
      <span>{!d ? "Đang kiểm…" : d.in_sync ? "Khớp — bản ClawCompany và gateway giống nhau" : `Lệch ${d.drift_count} mục`}</span></div>
      <div className="tmRow"><button className="ui-btn is-ghost is-sm" onClick={load} disabled={busy}>Kiểm tra lại</button>
        {canEdit && d && !d.in_sync && d.roster_match && <>
          <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => sync("push")} data-testid="hr-push-all">Đồng bộ lại · đẩy lên</button>
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("pull")} data-testid="hr-pull-all">Nhận bản gateway</button></>}</div></div>
    {err && <div className="ui-banner is-error">{err}</div>}
    {d?.warnings?.map((w: string, i: number) => <small key={i} className="tmGuide">{w}</small>)}
    {d && <table className="tmTable"><tbody>
      {(d.fields || []).map((f: any) => <tr key={f.field} className={f.match ? "" : "is-err"}>
        <td><b>{f.label}</b></td><td><small>ClawCompany: {f.clawcompany || "—"}<br/>Gateway: {f.gateway || "—"}</small></td>
        <td>{f.match ? "Khớp" : <span className="is-warn">Lệch</span>}</td>
        <td style={{textAlign: "right"}}>{!f.match && canEdit && <span className="tmRow">
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("push", [], [f.field])}>Đẩy lên</button>
          <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("pull", [], [f.field])}>Nhận về</button></span>}</td></tr>)}
      {(d.files || []).map((f: any) => <tr key={f.name} className={f.counts_as_drift ? "is-err" : ""} data-testid={`hr-file-${f.name}`}>
        <td><b>{f.name}</b>{f.agent_owned && <><br/><small>agent tự ghi</small></>}</td>
        <td><small>{FILE_VI[f.status] || f.status}{f.clawcompany_source === "gateway_accepted" ? " · bản đã nhận từ gateway" : ""}</small>
          {f.status === "edited_on_gateway" && <><br/><button className="hrLinkBtn" onClick={() => setOpen(open === f.name ? "" : f.name)}>{open === f.name ? "Ẩn so sánh" : "Xem khác biệt"}</button></>}</td>
        <td>{f.status === "in_sync" ? "Khớp" : f.counts_as_drift ? <span className="is-warn">Lệch</span> : <small>—</small>}</td>
        <td style={{textAlign: "right"}}>{canEdit && ["edited_on_gateway", "missing_on_gateway", "untracked"].includes(f.status) && <span className="tmRow">
          {f.status !== "untracked" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("push", [f.name], [])}>Đẩy lên</button>}
          {f.status !== "missing_on_gateway" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => sync("pull", [f.name], [])}>Nhận về</button>}</span>}</td></tr>)}
    </tbody></table>}
    {open && (() => { const f = d.files.find((x: any) => x.name === open); return f ? <DiffView a={f.clawcompany_content || ""} b={f.gateway_content || ""}/> : null; })()}
    {d && drifted.length === 0 && fieldsBad.length === 0 && d.roster_match && <small className="tmGuide">Sửa tay trên máy gateway (hoặc agent tự sửa) sẽ hiện ở đây; MEMORY.md do agent tự ghi nên không tính là lệch.</small>}
  </section>;
}

function DiffView({a, b}: {a: string; b: string}) {
  const rows = useMemo(() => {
    const A = a.split("\n"), B = b.split("\n"), setA = new Set(A), setB = new Set(B);
    return {left: A.map(l => ({l, gone: !setB.has(l)})), right: B.map(l => ({l, added: !setA.has(l)}))};
  }, [a, b]);
  return <div className="hrDiff" data-testid="hr-diff">
    <div><b>Bản ClawCompany</b><pre>{rows.left.map((r, i) => <span key={i} className={r.gone ? "is-gone" : ""}>{r.l || " "}</span>)}</pre></div>
    <div><b>Bản trên gateway</b><pre>{rows.right.map((r, i) => <span key={i} className={r.added ? "is-added" : ""}>{r.l || " "}</span>)}</pre></div>
  </div>;
}

function Tools({seat, isAdmin, busy, act, tick}: any) {
  const [t, setT] = useState<any>(null), [err, setErr] = useState("");
  useEffect(() => { apiAgentsHR.tools(seat.agent_id).then(setT).catch(e => setErr(errorText(e))); }, [seat.agent_id, tick]);
  const src = (s: string) => s === "member" ? "riêng ghế này" : s.startsWith("tier") ? "theo bậc" : s.startsWith("default") ? "mặc định" : s;
  return <section className="v8Card" data-testid="hr-tools">
    <div className="v8CardHead"><div><b>Quyền dùng tool công ty</b>
      <span>{t ? `Bậc ghế: ${t.tier_label}. Đặt riêng cho ghế này sẽ đè lên bậc và mặc định.` : "Đang tải…"}</span></div>
      <Link className="v8Ghost" href="/app/agent-tools">Ma trận theo bậc →</Link></div>
    {err && <div className="ui-banner is-error">{err}</div>}
    {t && <div className="hrScroll"><table className="tmTable"><tbody>{t.tools.map((x: any) => <tr key={x.name}>
      <td><b>{x.name}</b><br/><small>{x.description}</small></td>
      <td><small>{x.group}{x.writes ? " · ghi" : ""}</small></td>
      <td>{isAdmin && seat.lifecycle !== "retired" ? <select value={x.source === "member" ? x.level : "inherit"} disabled={busy} data-testid={`hr-tool-${x.name}`}
          onChange={e => act(() => apiMcp.setPermission({tool: x.name, level: e.target.value, member_id: seat.member_id}),
            () => `Đã đặt ${x.name} = ${e.target.value === "inherit" ? "theo bậc" : LEVEL_VI[e.target.value]}`)}>
          <option value="inherit">{x.source === "member" ? "Theo bậc / mặc định" : `Theo bậc / mặc định (${LEVEL_VI[x.level] || x.level})`}</option>
          {t.levels.map((l: string) => <option key={l} value={l}>{LEVEL_VI[l] || l}</option>)}</select>
        : <span className={x.level === "off" ? "is-warn" : ""}>{LEVEL_VI[x.level] || x.level}</span>}</td>
      <td><small>{src(x.source)}</small></td></tr>)}</tbody></table></div>}
    {t && !isAdmin && <small className="tmGuide">Đổi quyền tool cần vai Quản trị.</small>}
  </section>;
}
