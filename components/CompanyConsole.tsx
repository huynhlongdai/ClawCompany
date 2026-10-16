"use client";
// Mục "Công ty" (2026-10-16): mọi trang cấp công ty tách khỏi Đội ngũ — anh góp ý "gom
// nhóm công ty ra một menu lớn, đừng để trong Đội ngũ, như vậy quá rối".
// Không có component mới cho nội dung: mỗi tab dùng lại đúng component cũ (CompanyFoundation,
// CompanyOperations, AgentNative, Rental, TeamConsole.DepartmentsTab/BuildTab); chỉ thêm
// trang Tổng quan (danh sách công ty, đổi công ty đang xem, lưu trữ có xem trước).
import {useEffect, useMemo, useState} from "react";
import {useSearchParams} from "next/navigation";
import Link from "next/link";
import {PageFrame} from "./shell/PageFrame";
import {apiTeam, apiRental, apiV29} from "../lib/api";
import {CompanyProfileTab, PositionsTab, AuthorityTab} from "./CompanyFoundation";
import {ProcessesTab, KpiTab, RhythmTab, ComplianceTab, ReadinessTab} from "./CompanyOperations";
import {RulesTab, ContractsTab, CoverageTab, AgentWorkforceTab} from "./AgentNative";
import {CompanyRolesTab, LeaseOutTab, LeasedTab} from "./Rental";
import {DocLibraryTab, FactsTab, RecordsTab} from "./DocLibrary";
import {CatalogTab} from "./Catalog";
import {CustomersTab, PartnersTab, PrivacyTab} from "./Business";
import {DocIngestTab} from "./DocIngest";
import {DocLearningTab} from "./DocLearning";
import {DepartmentsTab, BuildTab, flatten} from "./TeamConsole";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {Icon} from "./Icon";
import {useCompanyId} from "../lib/prefs";
import {refreshCounts} from "../lib/counts";
import {COMPANY_TAB_IDS, type CompanyTab} from "../lib/nav";
import {t as tr, type Key} from "../lib/i18n";

export function CompanyConsole() {
  const params = useSearchParams();
  const raw = params.get("tab") as CompanyTab;
  const tab: CompanyTab = (COMPANY_TAB_IDS as readonly string[]).includes(raw) ? raw : "overview";
  const [pref, setPref] = useCompanyId();
  const [companyId, setCompanyId] = useState<number | null>(Number(params.get("company")) || pref || null);
  const [me, setMe] = useState<any>(null), [chart, setChart] = useState<any>(null);
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const caps = me?.capabilities || {};

  async function load(cid = companyId) {
    const [m, c] = await Promise.allSettled([apiTeam.me(), apiTeam.orgChart(cid)]);
    if (m.status === "fulfilled") setMe(m.value); else setError(m.reason);
    if (c.status === "fulfilled") { setChart(c.value); if (c.value?.company && cid == null) setCompanyId(c.value.company.id); } else setError(c.reason);
  }
  useEffect(() => { load(); }, []);
  /* ?company= trong link cũ (fix_href readiness, Inbox) thắng lựa chọn đang nhớ — đồng bộ một lần */
  useEffect(() => { const q = Number(params.get("company")); if (q && q !== pref) setPref(q); // eslint-disable-next-line
  }, []);
  useEffect(() => { if (pref && pref !== companyId) { setCompanyId(pref); load(pref); } // eslint-disable-next-line
  }, [pref]);
  async function act(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await load(); return r; }
    catch (e: any) { setError(e); } finally { setBusy(false); }
  }
  const pickCompany = (v: number) => { setCompanyId(v); setPref(v); load(v); };
  const members = useMemo(() => flatten(chart?.tree || []), [chart]);
  const needsChart = tab === "departments" || tab === "positions" || tab === "authority" || tab === "roles" || tab === "build";

  return <PageFrame actions={chart?.companies?.length > 1 ? <label className="tmInline">{tr("team.cong_ty")}
      <select value={companyId ?? ""} onChange={e => pickCompany(Number(e.target.value))} data-testid="company-select">
        {chart.companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select></label> : undefined}>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} onRetry={() => load()} testId="company-error"/> : null}
    {needsChart && !chart ? <SkeletonRows n={4}/> : <>
      {tab === "overview" && <OverviewTab companyId={companyId} caps={caps} onPick={pickCompany} reloadChart={() => load()}/>}
      {tab === "readiness" && <ReadinessTab companyId={companyId} caps={caps}/>}
      {tab === "build" && <BuildTab chart={chart} caps={caps} busy={busy} act={act} onCompany={(id: number) => pickCompany(id)}/>}
      {tab === "profile" && <CompanyProfileTab companyId={companyId} caps={caps}/>}
      {tab === "roles" && <CompanyRolesTab companyId={companyId} members={members}/>}
      {tab === "authority" && <AuthorityTab companyId={companyId} chart={chart} caps={caps}/>}
      {tab === "rules" && <RulesTab companyId={companyId} caps={caps}/>}
      {tab === "departments" && <DepartmentsTab chart={chart} members={members} caps={caps} busy={busy} act={act}/>}
      {tab === "positions" && <PositionsTab companyId={companyId} chart={chart} caps={caps}/>}
      {tab === "processes" && <ProcessesTab companyId={companyId} caps={caps}/>}
      {tab === "contracts" && <ContractsTab companyId={companyId} caps={caps}/>}
      {tab === "rhythm" && <RhythmTab companyId={companyId} caps={caps}/>}
      {tab === "coverage" && <CoverageTab companyId={companyId} caps={caps}/>}
      {tab === "compliance" && <ComplianceTab companyId={companyId} caps={caps}/>}
      {tab === "kpi" && <KpiTab companyId={companyId} caps={caps}/>}
      {tab === "agenthr" && <AgentWorkforceTab companyId={companyId} caps={caps}/>}
      {tab === "leaseout" && <LeaseOutTab companyId={companyId} caps={caps}/>}
      {tab === "leased" && <LeasedTab companyId={companyId} caps={caps}/>}
      {tab === "docs" && <DocLibraryTab companyId={companyId} caps={caps}/>}
      {tab === "ingest" && <DocIngestTab companyId={companyId} caps={caps}/>}
      {tab === "learning" && <DocLearningTab companyId={companyId} caps={caps}/>}
      {tab === "facts" && <FactsTab companyId={companyId} caps={caps}/>}
      {tab === "records" && <RecordsTab companyId={companyId} caps={caps}/>}
      {tab === "catalog" && <CatalogTab companyId={companyId} caps={caps}/>}
      {tab === "customers" && <CustomersTab companyId={companyId} caps={caps}/>}
      {tab === "privacy" && <PrivacyTab companyId={companyId} caps={caps}/>}
      {tab === "partners" && <PartnersTab companyId={companyId} caps={caps}/>}
    </>}
  </PageFrame>;
}

const ROLE_KEYS: Record<string, Key> = {owner: "rental.role_owner", manager: "rental.role_manager", approver: "rental.role_approver", viewer: "rental.role_viewer",
  admin: "team.quan_tri", member: "team.thanh_vien", guest: "team.khach"};

/* Tổng quan: công ty anh xem được (theo vai từng công ty), đổi công ty đang xem, lưu trữ
   (xem trước phạm vi trước khi ghi — v29), lối tắt tạo công ty và các trang cấp công ty cũ. */
function OverviewTab({companyId, caps, onPick, reloadChart}: {companyId: number | null; caps: any; onPick: (id: number) => void; reloadChart: () => void}) {
  const [data, setData] = useState<any>(null), [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<any>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const load = () => apiRental.myCompanies().then(setData).catch(setError);
  useEffect(() => { load(); }, []);
  async function look(id: number) {
    setBusy(true); setError(null);
    try { setPreview(await apiV29.archivePreview("companies", id)); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function archive() {
    if (!preview) return;
    setBusy(true); setError(null);
    try {
      await apiV29.archive("companies", preview.id);
      toast(tr("company2.archived", {p0: preview.name})); setPreview(null);
      await load(); refreshCounts().catch(() => {}); reloadChart();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  if (error && !data) return <ErrorBanner error={error} onRetry={load} testId="companies-error"/>;
  if (!data) return <SkeletonRows n={3} h={56}/>;
  const items: any[] = data.items || [];
  return <div className="ui-page-body">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <section className="ui-panel" data-testid="company-list">
      <header className="ui-panel-head"><div className="ui-grow"><h2>{tr("company2.list_title")}</h2>
        <p>{data.restricted ? tr("company2.list_restricted") : tr("company2.list_desc")}</p></div>
        <Link className="ui-btn is-primary is-sm" href="/onboarding"><Icon name="plus" size={14}/>{tr("company2.create")}</Link></header>
      {items.length ? <div className="ui-list">
        {items.map(c => { const on = c.id === companyId;
          return <div key={c.id} className="ui-row" data-testid={`company-row-${c.id}`}>
            <Icon name="building" size={16}/>
            <span className="ui-row-main"><span className="ui-row-title">{c.name} {on && <StatusPill tone="ok">{tr("company2.viewing")}</StatusPill>}</span>
              <span className="ui-row-meta">{tr("company2.your_role")}: {ROLE_KEYS[c.role] ? tr(ROLE_KEYS[c.role]) : c.role || "—"}</span></span>
            {!on && <button className="ui-btn is-ghost is-sm" onClick={() => onPick(c.id)} data-testid={`company-pick-${c.id}`}>{tr("company2.view")}</button>}
            {caps.create_company && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => look(c.id)} data-testid={`company-archive-${c.id}`}>{tr("company2.archive")}</button>}
          </div>; })}
      </div> : <EmptyState compact mood="chao" title={tr("team.chua_co_cong_ty_nao")}>{tr("team.dung_tu_mau_shop_agency")}</EmptyState>}
    </section>
    {preview && <section className="ui-panel" data-testid="company-archive-preview">
      <header className="ui-panel-head"><div className="ui-grow"><h2>{tr("company2.archive_q", {p0: preview.name})}</h2>
        <p>{tr("company2.archive_counts", {p0: preview.counts?.departments ?? 0, p1: preview.counts?.members ?? 0, p2: preview.counts?.agents ?? 0, p3: preview.counts?.projects ?? 0})}</p></div></header>
      <div className="ui-panel-body">
        {preview.blocked ? <p className="is-warn">{tr("company2.archive_blocked")}</p> : <p><small>{tr("company2.archive_note")}</small></p>}
        <div className="tmRow" style={{marginTop: 10}}>
          <button className="ui-btn is-danger" disabled={busy || preview.blocked || preview.already_archived} onClick={archive} data-testid="company-archive-confirm">{tr("company2.archive")}</button>
          <button className="ui-btn is-ghost" onClick={() => setPreview(null)}>{tr("company2.cancel")}</button>
        </div>
      </div>
    </section>}
    <section className="ui-panel">
      <header className="ui-panel-head"><div className="ui-grow"><h2>{tr("company2.tools_title")}</h2><p>{tr("company2.tools_desc")}</p></div></header>
      <div className="ui-list">
        <Link className="ui-row" href="/app/company?tab=readiness"><Icon name="check" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("nav.san_sang")}</span><span className="ui-row-meta">{tr("company2.readiness_meta")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/company?tab=build"><Icon name="plus" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("nav.co_tao_nhap")}</span><span className="ui-row-meta">{tr("company2.build_meta")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/company-factory"><Icon name="building" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("nav.dung_cong_ty_tu_mau")}</span><span className="ui-row-meta">{tr("nav.company_factory_doi_cu_dung")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/workspace-ops"><Icon name="pencil" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("nav.sua_du_lieu_to_chuc")}</span><span className="ui-row-meta">{tr("nav.lap_cong_ty_phong_ban")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/team"><Icon name="users" size={16}/><span className="ui-row-main"><span className="ui-row-title">{tr("nav.doi_ngu")}</span><span className="ui-row-meta">{tr("nav.doi_ngu_desc")}</span></span><Icon name="chevron-right" size={14}/></Link>
      </div>
    </section>
  </div>;
}
