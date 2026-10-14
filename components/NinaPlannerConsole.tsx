"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV8} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill, toneOf} from "./ui/StatusPill";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {useToast} from "./ui/Toast";
import {t, lazy} from "../lib/i18n";

/* Mục tiêu & Kế hoạch › Nina lập nhanh (v8 planner): đưa một kết quả, Nina chia
   thành các bước có người phụ trách và tạo việc ngay — không qua vòng duyệt.
   Muốn có duyệt theo phòng ban thì dùng tab "Kế hoạch chờ duyệt". */

type Plan = {id: number; objective: string; status: string; summary: string; created_at: string};
type Detail = {plan: Plan; steps: {id: number; step_index: number; title: string; description: string; owner_member_id: number | null; task_id: number | null; status: string}[]};
const ST_VI: Record<string, string> = lazy(() => ({planned: t("nina.da_lap"), delegated: t("nina.da_giao"), draft: t("nina.nhap"), completed: "Xong", pending: t("nina.cho"), in_progress: t("nina.dang_lam"), todo: t("nina.can_lam"), done: "Xong"}));

export function NinaPlannerConsole() {
  const org = activeOrganizationId();
  const toast = useToast();
  const [objective, setObjective] = useState(""), [companyId, setCompanyId] = useState(""), [projectId, setProjectId] = useState("");
  const [companies, setCompanies] = useState<any[]>([]), [projects, setProjects] = useState<any[]>([]), [plans, setPlans] = useState<Plan[]>([]);
  const [members, setMembers] = useState<Record<number, string>>({});
  const [detail, setDetail] = useState<Detail | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    const [c, p, pl, m] = await Promise.allSettled([api.companies(org), api.projects(), apiV8.ninaPlans(), api.members()]);
    if (c.status === "fulfilled") setCompanies((c.value as any[]) || []);
    if (p.status === "fulfilled") setProjects((p.value as any[]) || []);
    if (pl.status === "fulfilled") setPlans((pl.value as Plan[]) || []); else setError(pl.reason);
    if (m.status === "fulfilled") setMembers(Object.fromEntries(((m.value as any[]) || []).map(x => [x.id, x.name])));
  }, [org]);
  useEffect(() => { load(); }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const j = await apiV8.createNinaPlan({organization_id: org, objective, company_id: companyId ? Number(companyId) : null,
        project_id: projectId ? Number(projectId) : null, auto_create_tasks: true, max_steps: 5}) as Detail;
      setDetail(j); toast(t("nina.nina_da_lap_ke_hoach", {p0: j.plan.id, p1: j.steps.length})); setObjective(""); await load();
    } catch (e2) { setError(e2); } finally { setBusy(false); }
  }
  async function delegate() {
    if (!detail) return; setBusy(true); setError(null);
    try { await apiV8.delegateNinaPlan(detail.plan.id); setDetail({...detail, plan: {...detail.plan, status: "delegated"}}); toast(t("nina.da_giao_ke_hoach_cho")); await load(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function openPlan(id: number) {
    setError(null);
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"}/nina/plans/${id}`, {headers: {Authorization: `Bearer ${localStorage.getItem("clawcompany_token")}`}});
      if (!r.ok) throw Object.assign(new Error(await r.text()), {status: r.status});
      setDetail(await r.json());
    } catch (e) { setError(e); }
  }

  return <PageFrame>
    <section className="nina-hero"><span className="nina-orb" aria-hidden="true">N</span>
      <div><h2>{t("nina.dua_nina_ket_qua_khong")}</h2>
        <p>{t("nina.nina_chia_muc_tieu_thanh")} <Link className="ui-link" href="/app/strategy">{t("nina.ke_hoach_cho_duyet")}</Link>.</p></div></section>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} context={t("nina.lap_ke_hoach")}/> : null}
    <div className="ui-grid is-2">
      <Panel title={t("nina.muc_tieu_cho_nina")}>
        <form className="ui-form" onSubmit={create}>
          <Field label={t("nina.cong_ty_can_dat_dieu")}><textarea rows={4} value={objective} onChange={e => setObjective(e.target.value)} placeholder={t("nina.vd_chay_chien_dich_tiktok")}/></Field>
          <FormRow>
            <Field label={t("nina.cong_ty")}><select value={companyId} onChange={e => { setCompanyId(e.target.value); setProjectId(""); }}>
              <option value="">{t("nina.khong_gioi_han")}</option>{companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Field label={t("nina.du_an")}><select value={projectId} onChange={e => setProjectId(e.target.value)}>
              <option value="">{t("nina.nina_tao_du_an_moi")}</option>{projects.filter(p => !companyId || String(p.company_id) === companyId).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          </FormRow>
          <Button type="submit" variant="primary" busy={busy} disabled={objective.trim().length < 4}>{busy ? t("nina.nina_dang_lap") : t("nina.lap_ke_hoach")}</Button>
        </form>
      </Panel>
      <Panel title={detail ? t("nina.ke_hoach", {p0: detail.plan.id}) : t("nina.ke_hoach_gan_day")} desc={detail ? detail.plan.objective : t("nina.ke_hoach_2", {p0: plans.length})}
        actions={detail ? <>{detail.plan.status !== "delegated" && <Button size="sm" variant="primary" busy={busy} onClick={delegate}>{t("nina.giao_cho_doi")}</Button>}
          <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>{t("nina.danh_sach")}</Button></> : undefined} flush={!detail}>
        {detail ? <ol className="gl-steps">{detail.steps.map(s => <li key={s.id}>
            <div><b>{s.title}</b><small>{s.description}</small></div>
            <div style={{textAlign: "right"}}><StatusPill tone={toneOf(s.status)}>{ST_VI[s.status] || s.status}</StatusPill>
              <small>{s.owner_member_id ? members[s.owner_member_id] || `#${s.owner_member_id}` : t("nina.chua_co_nguoi")}{s.task_id ? <> · <Link href={`/app/work?peek=${s.task_id}`}>{t("nina.viec")}{s.task_id}</Link></> : null}</small></div>
          </li>)}</ol>
          : plans.length === 0 ? <EmptyState compact mood="chao" title={t("nina.chua_co_ke_hoach_nao")}>{t("nina.viet_muc_tieu_ben_trai")}</EmptyState>
          : <div className="ui-list">{plans.slice(0, 12).map(p => <button key={p.id} className="ui-row" onClick={() => openPlan(p.id)}>
              <span className="ui-row-main"><span className="ui-row-title">#{p.id} {p.objective}</span><span className="ui-row-meta">{p.summary}</span></span>
              <StatusPill tone={toneOf(p.status)}>{ST_VI[p.status] || p.status}</StatusPill></button>)}</div>}
      </Panel>
    </div>
  </PageFrame>;
}
