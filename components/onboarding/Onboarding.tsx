"use client";
import Link from "next/link";
import {useEffect, useState} from "react";
import {LogoLockup} from "../Logo";
import {BeCang} from "../BeCang";
import {Button, ButtonLink} from "../ui/Button";
import {Field} from "../ui/Field";
import {StatusPill, Tone} from "../ui/StatusPill";
import {ErrorBanner} from "../ui/EmptyState";
import {SkeletonRows} from "../ui/Skeleton";
import {apiTeam, apiV19, apiV9} from "../../lib/api";
import {activeOrganizationId} from "../../lib/auth";
import {refreshCounts} from "../../lib/counts";
import {useCompanyId} from "../../lib/prefs";
import {t as tr, lazy} from "../../lib/i18n";

/* Bốn bước: đặt tên công ty → chọn mẫu (dựng phòng ban + agent trưởng phòng)
   → kết nối OpenClaw (doctor) → giao việc đầu tiên cho Nina (mục tiêu → Nina lập kế hoạch).
   Mỗi bước gọi đúng API đã có (/api/team/companies/from-template, /api/v19/openclaw/doctor,
   /api/v9/goals); không thêm API mới. Bước 3 cho đi tiếp kể cả khi gateway chưa sẵn sàng
   — nói rõ agent sẽ chưa chạy được. */

const STEPS = lazy(() => ([tr("onboarding.ten_cong_ty"), tr("onboarding.chon_mau"), tr("onboarding.ket_noi_openclaw"), tr("onboarding.viec_dau_tien_cho_nina")]));
const DOC_TONE: Record<string, Tone> = {ok: "ok", warn: "wait", fail: "risk", skip: "neutral"};
const DOC_VI: Record<string, string> = lazy(() => ({ok: tr("onboarding.on"), warn: tr("onboarding.can_chu_y"), fail: tr("onboarding.loi"), skip: tr("onboarding.bo_qua")}));

export function Onboarding() {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [templates, setTemplates] = useState<any[] | null>(null), [tpl, setTpl] = useState("");
  const [company, setCompany] = useState<any>(null);
  const [doc, setDoc] = useState<any>(null), [docBusy, setDocBusy] = useState(false);
  const [goal, setGoal] = useState({title: "", objective: "", budget: "10"}), [goalDone, setGoalDone] = useState<any>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const [, setCompanyPref] = useCompanyId();

  useEffect(() => { apiTeam.templates().then((t: any) => { setTemplates(t || []); setTpl(t?.[0]?.key || ""); }).catch(e => { setTemplates([]); setError(e); }); }, []);
  const runDoctor = async () => { setDocBusy(true); try { setDoc(await apiV19.doctor()); } catch (e) { setDoc({status: "fail", checks: [{id: "api", label: tr("onboarding.goi_kiem_tra"), status: "fail", detail: String((e as any)?.message || e), fix: tr("onboarding.kiem_tra_dich_vu_api")}]}); } finally { setDocBusy(false); } };
  useEffect(() => { if (step === 2 && !doc) runDoctor(); }, [step, doc]);

  async function build() {
    setBusy(true); setError(null);
    try {
      const r = await apiTeam.fromTemplate(tpl, name.trim());
      setCompany(r); setCompanyPref(r.company_id); refreshCounts(); setStep(2);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function assign() {
    setBusy(true); setError(null);
    try {
      const g = await apiV9.createGoal({organization_id: activeOrganizationId(), company_id: company?.company_id ?? null, title: goal.title.trim(),
        objective: goal.objective.trim(), budget_limit: goal.budget ? Number(goal.budget) : null, currency: "USD"});
      setGoalDone(g); try { localStorage.setItem("cc_onboarded", "1"); } catch { /* bỏ qua */ }
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const t = templates?.find(x => x.key === tpl);

  return <div className="ob">
    <header className="ob-top"><LogoLockup/><Link href="/app/os" className="ui-link">{tr("onboarding.bo_qua_vao_app")}</Link></header>
    <div className="ob-body">
      <ol className="ob-steps" aria-label={tr("onboarding.cac_buoc")}>
        {STEPS.map((s, i) => <li key={s} className={i === step ? "is-on" : i < step ? "is-done" : ""} aria-current={i === step ? "step" : undefined}><span>{i + 1}</span>{s}</li>)}
      </ol>
      <section className="ob-card" aria-live="polite">
        {error ? <ErrorBanner error={error} onClose={() => setError(null)} context={tr("onboarding.dung_cong_ty")}/> : null}

        {step === 0 && <form className="ui-form" onSubmit={e => { e.preventDefault(); if (name.trim().length >= 2) setStep(1); }}>
          <div><h1>{tr("onboarding.cong_ty_cua_anh_ten")}</h1><p>{tr("onboarding.ten_hien_tren_menu_so")}</p></div>
          <Field label={tr("onboarding.ten_cong_ty")}><input value={name} onChange={e => setName(e.target.value)} placeholder={tr("onboarding.vd_tiem_gom_moc")} autoComplete="organization" autoFocus data-testid="ob-name"/></Field>
          <div className="ob-actions"><Button type="submit" variant="primary" disabled={name.trim().length < 2} data-testid="ob-next-0">{tr("onboarding.tiep_tuc")}</Button></div>
        </form>}

        {step === 1 && <div className="ui-form">
          <div><h1>{tr("onboarding.chon_mau_cong_ty")}</h1><p>{tr("onboarding.moi_mau_dung_san_phong")}</p></div>
          {!templates ? <SkeletonRows n={3} h={72}/> : <div className="ob-tpls" role="radiogroup" aria-label={tr("onboarding.mau_cong_ty")}>
            {templates.map(x => <button key={x.key} type="button" role="radio" aria-checked={tpl === x.key} className="ob-tpl" onClick={() => setTpl(x.key)} data-testid={`ob-tpl-${x.key}`}>
              <b>{x.name}</b><span>{x.description}</span>
              <small>{x.departments.length} {tr("onboarding.phong")} {x.agents} agent — {x.departments.map((d: any) => d.name).join(", ")}</small>
            </button>)}</div>}
          <div className="ob-actions"><Button onClick={() => setStep(0)}>{tr("onboarding.quay_lai")}</Button>
            <Button variant="primary" busy={busy} disabled={!tpl} onClick={build} data-testid="ob-build">{busy ? tr("onboarding.dang_dung") : tr("onboarding.dung", {p0: name.trim(), p1: t ? ` · ${t.agents} agent` : ""})}</Button></div>
        </div>}

        {step === 2 && <div className="ui-form">
          <div><h1>{tr("onboarding.ket_noi_openclaw")}</h1><p>{company ? tr("onboarding.da_dung_phong_agent_co", {p0: company.company_name, p1: company.departments, p2: company.agents_bound, p3: company.agents}) : ""}
            {tr("onboarding.kiem_tra_gateway_model_va")}</p></div>
          {!doc ? <SkeletonRows n={4} h={40}/> : <ol className="oc-checks ob-checks">{(doc.checks || []).map((c: any) => <li key={c.id} className={"oc-check is-" + c.status}>
            <StatusPill tone={DOC_TONE[c.status] || "neutral"}>{DOC_VI[c.status] || c.status}</StatusPill>
            <div className="oc-check-body"><b>{c.label}</b><span>{c.detail}</span>{c.fix && <span className="oc-fix">→ {c.fix}</span>}</div></li>)}</ol>}
          {doc && doc.status !== "ok" && <p className="ob-note">{tr("onboarding.co_the_di_tiep_cong")}</p>}
          <div className="ob-actions"><Button icon="pulse" busy={docBusy} onClick={runDoctor}>{tr("onboarding.kiem_tra_lai")}</Button>
            <Button variant="primary" onClick={() => setStep(3)} data-testid="ob-next-2">{tr("onboarding.tiep_tuc")}</Button></div>
        </div>}

        {step === 3 && !goalDone && <form className="ui-form" onSubmit={e => { e.preventDefault(); assign(); }}>
          <div><h1>{tr("onboarding.giao_viec_dau_tien_cho")}</h1><p>{tr("onboarding.nina_la_tro_ly_dieu")}</p></div>
          <Field label={tr("onboarding.muc_tieu")}><input value={goal.title} onChange={e => setGoal({...goal, title: e.target.value})} placeholder={tr("onboarding.vd_ra_mat_bo_suu")} autoComplete="off" data-testid="ob-goal"/></Field>
          <Field label={tr("onboarding.ket_qua_mong_doi")}><textarea rows={3} value={goal.objective} onChange={e => setGoal({...goal, objective: e.target.value})} placeholder={tr("onboarding.vd_50_don_dau_tien")}/></Field>
          <Field label={tr("onboarding.ngan_sach_cho_muc_tieu")} hint={tr("onboarding.chi_phi_model_toi_da")}><input type="number" min={0} inputMode="decimal" value={goal.budget} onChange={e => setGoal({...goal, budget: e.target.value})}/></Field>
          <div className="ob-actions"><Button onClick={() => setStep(2)}>{tr("onboarding.quay_lai")}</Button>
            <Button type="submit" variant="primary" busy={busy} disabled={goal.title.trim().length < 2 || goal.objective.trim().length < 4} data-testid="ob-assign">Giao cho Nina</Button></div>
        </form>}

        {step === 3 && goalDone && <div className="ob-done">
          <BeCang mood="done" size={120}/>
          <h1>{tr("onboarding.xong_nina_da_nhan_muc")}{goalDone.id}</h1>
          <p>{tr("onboarding.ke_hoach_se_hien_o")}</p>
          <div className="ob-actions"><ButtonLink href="/app/strategy" variant="primary">{tr("onboarding.xem_ke_hoach")}</ButtonLink><ButtonLink href="/app/os">{tr("onboarding.vao_tong_quan")}</ButtonLink></div>
        </div>}
      </section>
    </div>
  </div>;
}
