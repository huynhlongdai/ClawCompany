"use client";
// M2 — Đội ngũ: sơ đồ tổ chức theo quản lý, người & quyền (mời / đổi vai / thu
// hồi), phòng ban (trưởng phòng, người quản lý), tạo công ty từ mẫu & nhập CSV.
// Mọi nút đều theo /api/team/me.capabilities — người không đủ quyền thấy giải
// thích thay vì nút bấm rồi mới bị 403.
import {useEffect, useMemo, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {PageFrame} from "./shell/PageFrame";
import {apiTeam, errorText} from "../lib/api";
import {AgentHRTab} from "./AgentHR";
import {LearningHub} from "./LearningHub";
import {CompanyProfileTab, PositionsTab, AuthorityTab} from "./CompanyFoundation";
import {ProcessesTab, KpiTab, RhythmTab, ComplianceTab, ReadinessTab} from "./CompanyOperations";
import {RulesTab, ContractsTab, CoverageTab} from "./AgentNative";
import {Notice, EmptyState, ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Icon} from "./Icon";
import Link from "next/link";
import {useCompanyId} from "../lib/prefs";
import {t as tr, lazy} from "../lib/i18n";

type Tab = "chart" | "people" | "departments" | "ai" | "training" | "build" | "profile" | "positions" | "authority" | "processes" | "kpi" | "rhythm" | "compliance" | "readiness" | "rules" | "contracts" | "coverage";
const TAB_IDS: Tab[] = ["chart", "people", "departments", "ai", "training", "build", "profile", "positions", "authority", "processes", "kpi", "rhythm", "compliance", "readiness", "rules", "contracts", "coverage"];
const ROLE_VI: Record<string, string> = lazy(() => ({guest: tr("team.khach"), member: tr("team.thanh_vien"), manager: tr("team.quan_ly"), admin: tr("team.quan_tri"), owner: tr("team.chu_so_huu")}));
const CSV_SAMPLE = `tên,loại,chức danh,phòng ban,quản lý,email,trưởng phòng
Hà,người,Giám đốc,Ban điều hành,,ha@congty.vn,x
Minh,người,Trưởng kho,Kho,Hà,minh@congty.vn,x
Bot đóng gói,agent,Đóng gói đơn,Kho,Minh,,`;

function Node({n}: {n: any}) {
  const pending = n.status === "pending_runtime" || n.lifecycle === "runtime_missing";
  const agent = n.type === "agent";
  const inner = <>
    <span className={"ui-ava is-lg " + (agent ? "is-agent" : "is-human")} aria-hidden="true">{agent ? <Icon name="sparkle" size={16} strokeWidth={2}/> : (n.name || "?").slice(0, 1).toUpperCase()}</span>
    <span><b>{n.name}</b><small>{n.role || "—"}</small>{n.department && <span className="org-dept">{n.department}{n.access_role ? ` · ${ROLE_VI[n.access_role] || n.access_role}` : ""}</span>}</span>
    {(pending || n.cycle) ? <span className="org-flag is-warn">{pending ? tr("team.chua_co_tren_gateway") : tr("team.vong_quan_ly")}</span>
      : n.is_head ? <span className="org-flag">{tr("team.truong_phong")}</span> : null}
  </>;
  const cls = "org-node" + (n.is_head ? " is-head" : "") + (agent ? " is-agent" : "");
  return <li>
    {agent ? <Link href={`/app/agents/${n.id}`} className={cls} data-testid={`node-${n.id}`}>{inner}</Link>
      : <div className={cls} data-testid={`node-${n.id}`}>{inner}</div>}
    {n.children?.length > 0 && <ul>{n.children.map((c: any) => <Node key={c.id} n={c}/>)}</ul>}
  </li>;
}

function flatten(tree: any[]): any[] {
  const out: any[] = []; const walk = (ns: any[]) => ns.forEach(n => { out.push(n); walk(n.children || []); });
  walk(tree || []); return out;
}

export function TeamConsole() {
  const router = useRouter(); const params = useSearchParams();
  const raw = params.get("tab") as Tab;
  const tab: Tab = TAB_IDS.includes(raw) ? raw : "chart";
  const [pref, setPref] = useCompanyId();
  const [companyId, setCompanyId] = useState<number | null>(Number(params.get("company")) || pref || null);
  const [me, setMe] = useState<any>(null), [chart, setChart] = useState<any>(null), [people, setPeople] = useState<any>(null);
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const caps = me?.capabilities || {};

  async function load(cid = companyId) {
    /* ba nguồn song song (trước v2: people gọi sau khi me + sơ đồ về — một nhịp chờ thừa) */
    const [m, c, p] = await Promise.allSettled([apiTeam.me(), apiTeam.orgChart(cid), apiTeam.people()]);
    if (m.status === "fulfilled") setMe(m.value); else setError(m.reason);
    if (c.status === "fulfilled") { setChart(c.value); if (c.value?.company && cid == null) setCompanyId(c.value.company.id); } else setError(c.reason);
    setPeople(p.status === "fulfilled" ? p.value : null);
  }
  useEffect(() => { load(); }, []);
  /* bộ đổi công ty ở sidebar → đổi sơ đồ theo */
  useEffect(() => { if (pref && pref !== companyId) { setCompanyId(pref); load(pref); } // eslint-disable-next-line
  }, [pref]);
  async function act(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await load(); return r; }
    catch (e: any) { setError(e); } finally { setBusy(false); }
  }
  const pickCompany = (v: number) => { setCompanyId(v); setPref(v); load(v); };
  const setTab = (t: Tab) => router.replace(`/app/team?tab=${t}${companyId ? `&company=${companyId}` : ""}`);

  const members = useMemo(() => flatten(chart?.tree || []), [chart]);
  return <PageFrame actions={chart?.companies?.length > 1 ? <label className="tmInline">{tr("team.cong_ty")}
      <select value={companyId ?? ""} onChange={e => pickCompany(Number(e.target.value))} data-testid="team-company">
        {chart.companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select></label> : undefined}>
    {me && tab !== "chart" && <Notice testId="team-role">
      {tr("team.anh_dang_la")} <b>{me.role_label}</b> trong {me.organization || tr("team.to_chuc")}.{" "}
      {caps.manage_roles ? tr("team.anh_moi_nguoi_doi_vai")
        : caps.invite ? tr("team.anh_moi_thanh_vien_va")
        : tr("team.anh_xem_duoc_so_do")}
    </Notice>}
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} onRetry={() => load()} testId="team-error"/> : null}

    {tab === "chart" && <ChartTab chart={chart} onBuild={() => setTab("build")}/>}
    {tab === "people" && <PeopleTab me={me} people={people} chart={chart} busy={busy} act={act}/>}
    {tab === "departments" && <DepartmentsTab chart={chart} members={members} caps={caps} busy={busy} act={act}/>}
    {tab === "ai" && <AgentHRTab companyId={companyId} caps={caps}/>}
    {tab === "training" && <TrainingTab/>}
    {tab === "profile" && <CompanyProfileTab companyId={companyId} caps={caps}/>}
    {tab === "positions" && <PositionsTab companyId={companyId} chart={chart} caps={caps}/>}
    {tab === "authority" && <AuthorityTab companyId={companyId} chart={chart} caps={caps}/>}
    {tab === "processes" && <ProcessesTab companyId={companyId} caps={caps}/>}
    {tab === "kpi" && <KpiTab companyId={companyId} caps={caps}/>}
    {tab === "rhythm" && <RhythmTab companyId={companyId} caps={caps}/>}
    {tab === "compliance" && <ComplianceTab companyId={companyId} caps={caps}/>}
    {tab === "readiness" && <ReadinessTab companyId={companyId} caps={caps}/>}
    {tab === "rules" && <RulesTab companyId={companyId} caps={caps}/>}
    {tab === "contracts" && <ContractsTab companyId={companyId} caps={caps}/>}
    {tab === "coverage" && <CoverageTab companyId={companyId} caps={caps}/>}
    {tab === "build" && <BuildTab chart={chart} caps={caps} busy={busy} act={act} onCompany={(id: number) => { pickCompany(id); setTab("chart"); }}/>}
  </PageFrame>;
}

function TrainingTab() {
  return <><LearningHub/><TrainingLinks/></>;
}

function TrainingLinks() {
  return <div style={{marginTop: 16}}>
    <section className="ui-panel"><header className="ui-panel-head"><div className="ui-grow"><h2>{tr("team.dung_duoc_ngay")}</h2><p>{tr("team.nhung_phan_dao_tao_da")}</p></div></header>
      <div className="ui-list">
        <Link className="ui-row" href="/app/agent-tools"><Icon name="shield" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("team.ky_nang_cong_cu")}</span><span className="ui-row-meta">{tr("team.cong_cu_agent_duoc_goi")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/team?tab=ai"><Icon name="sparkle" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("team.ho_so_agent")}</span><span className="ui-row-meta">{tr("team.sua_tinh_cach_soul_mo")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/memory"><Icon name="book" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("team.bo_nho_to_chuc")}</span><span className="ui-row-meta">{tr("team.quyet_dinh_va_tri_thuc")}</span></span><Icon name="chevron-right" size={14}/></Link>
      </div>
    </section>
  </div>;
}

function ChartTab({chart, onBuild}: {chart: any; onBuild: () => void}) {
  if (!chart) return <SkeletonRows n={4} h={64}/>;
  if (!chart.company) return <EmptyState mood="chao" title={tr("team.chua_co_cong_ty_nao")} action={<button className="ui-btn is-primary" onClick={onBuild}>{tr("team.dung_cong_ty_tu_mau")}</button>}>
    {tr("team.dung_tu_mau_shop_agency")}</EmptyState>;
  const s = chart.stats || {};
  return <section className="ui-section" data-testid="org-chart">
    <div className="ui-toolbar">
      <div className="org-stats"><span><b>{s.departments}</b> {tr("team.phong_ban")}</span><span><b>{s.humans}</b> {tr("team.nguoi")}</span><span><b>{s.agents}</b> agent</span>
        {s.without_head ? <span className="is-warn"><b>{s.without_head}</b> {tr("team.phong_chua_co_truong_phong")}</span> : null}</div>
      <span className="ui-grow"/>
      <div className="org-legend"><span><span className="ui-ava is-agent" style={{width: 14, height: 14}}/>{tr("team.agent_bam_de_mo_ho")}</span><span><span className="ui-ava is-human" style={{width: 14, height: 14}}/>{tr("team.nguoi_2")}</span></div>
    </div>
    <div className="org" data-testid="org-tree" ref={el => { /* sơ đồ rộng hơn màn hình (điện thoại): mở ra ở giữa, gốc công ty nằm trong tầm nhìn */ if (el && el.scrollWidth > el.clientWidth && !el.dataset.centered) { el.dataset.centered = "1"; el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2; } }}>
      {chart.tree.length ? <ul className="org-tree"><li>
        <div className="org-node is-root"><span className="ui-ava is-lg" aria-hidden="true"><Icon name="building" size={18}/></span>
          <span><b>{chart.company.name}</b><small>{s.departments} {tr("team.phong")} {(s.humans || 0) + (s.agents || 0)} {tr("team.thanh_vien_2")}</small></span></div>
        <ul>{chart.tree.map((n: any) => <Node key={n.id} n={n}/>)}</ul>
      </li></ul> : <EmptyState compact mood="ngu" title={tr("team.cong_ty_chua_co_thanh")}>{tr("team.moi_nguoi_o_tab_nguoi")}</EmptyState>}
    </div>
  </section>;
}

function PeopleTab({me, people, chart, busy, act}: any) {
  const caps = me?.capabilities || {};
  const [email, setEmail] = useState(""), [role, setRole] = useState("member"), [title, setTitle] = useState("");
  const [dept, setDept] = useState(""), [link, setLink] = useState("");
  if (!people) return <SkeletonRows n={4}/>;
  const roles: string[] = people.assignable_roles || [];
  async function invite() {
    const r = await act(() => apiTeam.invite({email, role, job_title: title, company_id: chart?.company?.id || null,
      department_id: dept ? Number(dept) : null}), (x: any) => tr("team.da_tao_loi_moi_cho", {p0: x.email, p1: x.role_label}));
    if (r?.invite_path) { setLink(window.location.origin + r.invite_path); setEmail(""); setTitle(""); }
  }
  return <div className="ui-grid is-2">
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>{tr("team.nguoi_co_quyen")}</b><span>{tr("team.vai_quyet_dinh_ai_duoc")}</span></div></div>
      <table className="ui-table" data-testid="people-table"><tbody>
        {people.users.map((u: any) => <tr key={u.user_id} className={u.status !== "is-active" ? "is-off" : ""}>
          <td><b>{u.display_name || u.email}</b>{u.is_self && tr("team.ban")}<br/><small>{u.email}{u.member_name ? tr("team.ghe", {p0: u.member_name}) : ""}</small></td>
          <td>{u.status !== "active" ? <small>{tr("team.da_thu_hoi")}</small> : u.editable
            ? <select value={u.role} disabled={busy} data-testid={`role-${u.user_id}`}
                onChange={e => act(() => apiTeam.setRole(u.user_id, e.target.value), tr("team.da_doi_vai", {p0: u.email, p1: ROLE_VI[e.target.value]}))}>
                {Array.from(new Set([...roles, u.role])).map((r: string) => <option key={r} value={r}>{ROLE_VI[r] || r}</option>)}
              </select>
            : <small>{u.role_label}</small>}</td>
          <td style={{textAlign: "right"}}>{u.editable && <button className="ui-btn is-ghost is-sm" disabled={busy}
            onClick={() => confirm(tr("team.thu_hoi_quyen_cua_phien", {p0: u.email})) && act(() => apiTeam.revokeAccess(u.user_id), tr("team.da_thu_hoi_quyen", {p0: u.email}))}>{tr("team.thu_hoi")}</button>}</td>
        </tr>)}
      </tbody></table>
    </section>
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>{tr("team.moi_nguoi")}</b><span>{caps.invite ? tr("team.tao_link_moi_nguoi_nhan") : tr("team.can_vai_quan_ly_tro")}</span></div></div>
      {caps.invite && <div className="ui-form">
        <div className="ui-form-row">
          <label>Email<input value={email} onChange={e => setEmail(e.target.value)} placeholder="ten@congty.vn" data-testid="invite-email"/></label>
          <label>Vai<select value={role} onChange={e => setRole(e.target.value)} data-testid="invite-role">
            {roles.map((r: string) => <option key={r} value={r}>{ROLE_VI[r]}</option>)}</select></label>
        </div>
        <div className="ui-form-row">
          <label>{tr("team.chuc_danh")}<input value={title} onChange={e => setTitle(e.target.value)} placeholder={tr("team.vd_nhan_vien_ban_hang")}/></label>
          <label>{tr("team.phong_ban_2")}<select value={dept} onChange={e => setDept(e.target.value)} data-testid="invite-dept">
            <option value="">{tr("team.chua_xep")}</option>
            {(chart?.departments || []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        </div>
        <button className="ui-btn is-primary" disabled={busy || !email} onClick={invite} data-testid="invite-submit">{tr("team.tao_loi_moi")}</button>
        {link && <div className="tmLink" data-testid="invite-link"><code>{link}</code>
          <button className="ui-btn is-ghost is-sm" onClick={() => navigator.clipboard?.writeText(link)}>{tr("team.sao_chep")}</button></div>}
      </div>}
      <b style={{display: "block", marginTop: 14, fontSize: 13}}>{tr("team.loi_moi_gan_day")}</b>
      <div className="tm-list" data-testid="invite-list">
        {people.invitations.slice(0, 12).map((i: any) => <div key={i.id} className="tmInvite">
          <span><b>{i.email}</b> · {i.role_label}{i.job_title ? ` · ${i.job_title}` : ""}</span>
          <small className={`is-${i.status}`}>{({pending: tr("team.dang_cho"), accepted: tr("team.da_nhan"), revoked: tr("team.da_thu_hoi"), expired: tr("team.het_han")} as any)[i.status] || i.status}</small>
          {i.status === "pending" && caps.invite && <button className="ui-btn is-ghost is-sm" disabled={busy}
            onClick={() => act(() => apiTeam.revokeInvite(i.id), tr("team.da_thu_hoi_loi_moi", {p0: i.email}))}>{tr("team.thu_hoi")}</button>}
        </div>)}
        {!people.invitations.length && <div className="ui-empty-line">{tr("team.chua_co_loi_moi_nao")}</div>}
      </div>
    </section>
  </div>;
}

function DepartmentsTab({chart, members, caps, busy, act}: any) {
  if (!chart?.company) return <EmptyState compact mood="chao" title={tr("team.chua_co_cong_ty")}>{tr("team.dung_cong_ty_o_tab")}</EmptyState>;
  const can = !!caps.edit_org_chart;
  return <div className="tmDepts" data-testid="dept-list">
    {!can && <div className="ui-banner">{tr("team.ban_dang_xem_chon_truong")}</div>}
    {chart.departments.map((d: any) => {
      const inDept = members.filter((m: any) => m.department_id === d.id);
      return <section key={d.id} className="ui-panel tm-card" data-testid={`dept-${d.id}`}>
        <div className="tm-card-head"><div><b>{d.name}</b><span>{d.humans} {tr("team.nguoi_3")} {d.agents} agent</span></div></div>
        <label className="tmInline">{tr("team.truong_phong")}
          <select value={d.head_member_id ?? ""} disabled={!can || busy} data-testid={`head-${d.id}`}
            onChange={e => act(() => apiTeam.setHead(d.id, e.target.value ? Number(e.target.value) : null),
              (r: any) => tr("team.da_dat_truong_phong", {p0: d.name, p1: r.reassigned ? ` · ${r.reassigned} người chuyển sang báo cáo trưởng phòng mới` : ""}))}>
            <option value="">{tr("team.chua_co")}</option>
            {members.map((m: any) => <option key={m.id} value={m.id}>{m.name}{m.department_id !== d.id ? ` (${m.department || tr("team.chua_xep_2")})` : ""}</option>)}
          </select></label>
        {d.guide && <small className="tmGuide">{d.guide}</small>}
        <table className="ui-table"><tbody>
          {inDept.map((m: any) => <tr key={m.id}>
            <td><b>{m.name}</b>{m.is_head && tr("team.truong_phong_2")}<br/><small>{m.role || "—"} · {m.type === "agent" ? "AI" : tr("team.nguoi")}</small></td>
            <td style={{textAlign: "right"}}><label className="tmInline">{tr("team.bao_cao_cho")}
              <select value={m.manager_id ?? ""} disabled={!can || busy} data-testid={`mgr-${m.id}`}
                onChange={e => act(() => apiTeam.setManager(m.id, e.target.value ? Number(e.target.value) : null), tr("team.da_doi_nguoi_quan_ly", {p0: m.name}))}>
                <option value="">{tr("team.khong_ai")}</option>
                {members.filter((x: any) => x.id !== m.id).map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select></label></td>
          </tr>)}
          {!inDept.length && <tr><td><small>{tr("team.phong_chua_co_ai")}</small></td></tr>}
        </tbody></table>
      </section>;
    })}
  </div>;
}

function BuildTab({chart, caps, busy, act, onCompany}: any) {
  const [templates, setTemplates] = useState<any[]>([]), [name, setName] = useState<Record<string, string>>({});
  const [result, setResult] = useState<any>(null), [csv, setCsv] = useState(CSV_SAMPLE), [report, setReport] = useState<any>(null);
  useEffect(() => { apiTeam.templates().then(setTemplates).catch(() => {}); }, []);
  const can = !!caps.create_company;
  async function build(key: string) {
    const r = await act(() => apiTeam.fromTemplate(key, name[key] || ""), (x: any) =>
      tr("team.da_dung_phong_ban_agent", {p0: x.company_name, p1: x.departments, p2: x.agents_bound, p3: x.agents}));
    if (r) setResult(r);
  }
  async function runCsv(dry: boolean) {
    const r = await act(() => apiTeam.importCsv(chart.company.id, csv, dry), (x: any) => x.dry_run
      ? (x.ok ? tr("team.kiem_tra_xong_tao_moi", {p0: x.summary.create, p1: x.summary.update}) : tr("team.co_dong_loi_sua_roi", {p0: x.summary.errors}))
      : x.applied ? tr("team.da_nhap_vao", {p0: chart.company.name}) : tr("team.chua_nhap_vi_con_loi"));
    if (r) setReport(r);
  }
  return <div className="ui-grid is-2">
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>{tr("team.tao_cong_ty_tu_mau")}</b><span>{can ? tr("team.moi_phong_co_truong_phong") : tr("team.can_vai_quan_tri_de")}</span></div></div>
      <div className="tm-list">
        {templates.map(t => <div key={t.key} className="tmTpl" data-testid={`tpl-${t.key}`}>
          <b>{t.name}</b><small>{t.description}</small>
          <small>{t.departments.map((d: any) => `${d.name} (${[d.head, ...d.staff].join(", ")})`).join(" · ")}</small>
          {can && <div className="tmRow">
            <input value={name[t.key] || ""} onChange={e => setName({...name, [t.key]: e.target.value})} placeholder={tr("team.ten_cong_ty_mac_dinh", {p0: t.name})}/>
            <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => build(t.key)} data-testid={`tpl-build-${t.key}`}>
              {busy ? tr("team.dang_dung") : tr("team.dung_agent", {p0: t.agents})}</button>
          </div>}
        </div>)}
      </div>
      {result && <div className="tmResult" data-testid="tpl-result">
        <b>{result.company_name}</b> {tr("team.viec")}{result.job_id} · {result.job_status === "ready" ? "xong" : tr("team.mot_phan")}
        {result.runtime_issues?.map((i: any) => <small key={i.runtime_agent_id} className="is-warn">⚠ {i.runtime_agent_id}: {i.hint || i.lifecycle}</small>)}
        <button className="ui-btn is-ghost is-sm" onClick={() => onCompany(result.company_id)}>{tr("team.xem_so_do")}</button>
      </div>}
    </section>
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>{tr("team.nhap_so_do_tu_csv")}</b><span>{tr("team.vao")} {chart?.company?.name || tr("team.cong_ty_dang_chon")} {tr("team.cot_ten_loai_chuc_danh")}</span></div></div>
      {can ? <div className="ui-form">
        <textarea rows={8} value={csv} onChange={e => { setCsv(e.target.value); setReport(null); }} data-testid="csv-text" style={{width: "100%", fontFamily: "var(--font-mono)", fontSize: 12}}/>
        <div className="tmRow">
          <label className="ui-btn is-ghost is-sm">{tr("team.chon_file_csv")}<input type="file" accept=".csv,text/csv" hidden
            onChange={async e => { const f = e.target.files?.[0]; if (f) { setCsv(await f.text()); setReport(null); } }}/></label>
          <button className="ui-btn is-ghost" disabled={busy || !chart?.company} onClick={() => runCsv(true)} data-testid="csv-check">{tr("team.kiem_tra")}</button>
          <button className="ui-btn is-primary" disabled={busy || !report?.ok || !report?.dry_run} onClick={() => runCsv(false)} data-testid="csv-apply">{tr("team.nhap")}</button>
        </div>
        <small>{tr("team.nguoi_co_email_se_nhan")}</small>
      </div> : <div className="ui-empty">{tr("team.can_vai_quan_tri_de_2")}</div>}
      {report && <div className="tmReport" data-testid="csv-report">
        <small>{report.summary.rows} {tr("team.dong")} {report.summary.create} {tr("team.tao_moi")} {report.summary.update} {tr("team.cap_nhat")} {report.summary.agents} agent · {report.summary.invitations} {tr("team.loi_moi")}
          {report.summary.departments_new?.length ? tr("team.phong_moi", {p0: report.summary.departments_new.join(", ")}) : ""}</small>
        <table className="ui-table"><tbody>
          {report.rows.map((r: any) => <tr key={r.line} className={r.errors.length ? "is-err" : ""}>
            <td><small>{tr("team.dong_2")} {r.line}</small></td><td><b>{r.name || "—"}</b> <small>{r.type === "agent" ? "AI" : tr("team.nguoi")} · {r.department || tr("team.chua_xep_2")}{r.manager ? ` → ${r.manager}` : ""}{r.is_head ? tr("team.truong_phong_2") : ""}</small></td>
            <td><small>{r.errors.length ? r.errors.join("; ") : r.action === "create" ? tr("team.tao_moi_2") : tr("team.cap_nhat_2")}{r.warnings.length ? ` (${r.warnings.join("; ")})` : ""}</small></td>
          </tr>)}
        </tbody></table>
        {report.invitations?.length > 0 && <div className="tmLink"><b>{tr("team.link_moi_chi_hien_mot")}</b>
          {report.invitations.map((i: any) => <code key={i.id}>{i.name}: {typeof window !== "undefined" ? window.location.origin : ""}/invite/{i.token}</code>)}</div>}
      </div>}
    </section>
  </div>;
}
