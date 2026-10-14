"use client";
import Link from "next/link";
import {useCallback, useEffect, useMemo, useState} from "react";
import {GoalTasks} from "./TaskGraphPanels";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV9} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill, toneOf} from "./ui/StatusPill";
import {Dialog} from "./ui/Dialog";
import {EmptyState, ErrorBanner, ErrorState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {t, lazy} from "../lib/i18n";

/* Mục tiêu & Kế hoạch › Mục tiêu (v9 executive goals).
   Một mục tiêu đi qua: tạo → Nina lập kế hoạch (tạo việc con) → chạy vòng vận
   hành có cổng (rủi ro → duyệt, ngân sách mỗi lượt) → nhịp đối soát.
   UI v2: viết lại tiếng Việt trên primitive; hành vi API giữ nguyên. */

const STATUS_VI: Record<string, string> = lazy(() => ({draft: t("goals.moi_tao"), planned: t("goals.da_lap_ke_hoach"), plan_pending: t("goals.ke_hoach_cho_duyet"), plan_revision: t("goals.nina_dang_sua"),
  plan_rejected: t("goals.ke_hoach_bi_tu_choi"), active: t("goals.dang_chay"), running: t("goals.dang_chay"), completed: t("goals.hoan_thanh"), cancelled: t("goals.da_huy"), blocked: t("goals.bi_chan"), waiting_approval: t("goals.cho_duyet")}));
const RISK_VI: Record<string, string> = lazy(() => ({low: t("goals.thap"), medium: t("goals.vua"), high: "Cao", critical: t("goals.nghiem_trong")}));
const CYCLE_VI: Record<string, string> = lazy(() => ({running: t("goals.dang_chay"), waiting_approval: t("goals.cho_duyet"), completed: "Xong", failed: t("goals.loi"), cancelled: t("goals.da_huy"), blocked: t("goals.bi_chan"), queued: t("goals.dang_cho")}));

export function GoalsConsole() {
  const org = activeOrganizationId();
  const toast = useToast();
  const [goals, setGoals] = useState<any[] | null>(null), [companies, setCompanies] = useState<any[]>([]), [cycles, setCycles] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null), [actErr, setActErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false), [creating, setCreating] = useState(false);
  const [form, setForm] = useState({title: "", objective: "", company_id: "", risk: "low", budget: "25"});

  const load = useCallback(async () => {
    setLoadErr(null);
    const [g, c, cy] = await Promise.allSettled([apiV9.goals(), api.companies(org), apiV9.cycles()]);
    if (g.status === "fulfilled") { const list = (g.value as any[]) || []; setGoals(list); setSelected((s: any) => s ?? list[0] ?? null); } else { setLoadErr(g.reason); setGoals([]); }
    if (c.status === "fulfilled") setCompanies((c.value as any[]) || []);
    if (cy.status === "fulfilled") setCycles((cy.value as any[]) || []);
  }, [org]);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<any>, ok: (r: any) => string) {
    setBusy(true); setActErr(null);
    try { const r = await fn(); toast(ok(r)); await load(); return r; } catch (e) { setActErr(e); } finally { setBusy(false); }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    const g = await act(() => apiV9.createGoal({organization_id: org, company_id: form.company_id ? Number(form.company_id) : null, title: form.title.trim(),
      objective: form.objective.trim(), expected_outcome: "", priority: "high", risk: form.risk, autonomy_mode: "inherit", deadline: "",
      budget_limit: form.budget ? Number(form.budget) : null, currency: "USD"}), (x: any) => t("goals.da_tao_muc_tieu", {p0: x.id}));
    if (g) { setSelected(g); setCreating(false); setForm(f => ({...f, title: "", objective: ""})); }
  }
  const plan = (g: any) => act(() => apiV9.planGoal(g.id, {max_steps: 5, project_id: null, auto_create_tasks: true}),
    (r: any) => { if (r?.goal?.id) setSelected(r.goal); return t("goals.nina_da_lap_ke_hoach"); });
  const run = (g: any) => act(() => apiV9.runGoal(g.id, {estimated_cost_per_assignment: 0.25, execute_unassigned: false}),
    (r: any) => t("goals.vong_van_hanh", {p0: r?.cycle?.id, p1: CYCLE_VI[r?.cycle?.status] || r?.cycle?.status || "đã bắt đầu"}));
  const tick = (c: any) => act(() => apiV9.tickCycle(c.id, true), () => t("goals.da_doi_soat_vong", {p0: c.id}));

  const shownCycles = useMemo(() => cycles.filter(c => !selected || c.goal_id === selected.id).slice(0, 12), [cycles, selected]);
  const valid = form.title.trim().length >= 2 && form.objective.trim().length >= 4;

  return <PageFrame action={<Button variant="primary" icon="plus" onClick={() => setCreating(true)} data-testid="goal-new">{t("goals.muc_tieu_moi")}</Button>}>
    {actErr ? <ErrorBanner error={actErr} onClose={() => setActErr(null)} context={t("goals.thao_tac_voi_muc_tieu")}/> : null}
    <div className="ui-grid is-side">
      <Panel title={t("goals.muc_tieu")} desc={goals ? t("goals.muc_tieu_trong_to_chuc", {p0: goals.length}) : t("goals.dang_tai")} flush testId="goals-list">
        {loadErr ? <ErrorState error={loadErr} onRetry={load} context={t("goals.tai_muc_tieu")} compact/>
          : !goals ? <div className="ui-panel-body"><SkeletonRows n={4}/></div>
          : goals.length === 0 ? <EmptyState mood="chao" title={t("goals.chua_co_muc_tieu")} action={<Button variant="primary" onClick={() => setCreating(true)}>{t("goals.dat_muc_tieu_dau_tien")}</Button>}>
              {t("goals.dua_ra_ket_qua_muon")}</EmptyState>
          : <div className="ui-list">{goals.map(g => <div key={g.id} className={"ui-row gl-row" + (selected?.id === g.id ? " is-on" : "")}>
              <button className="gl-pick" onClick={() => setSelected(g)} aria-pressed={selected?.id === g.id}>
                <span className="ui-row-main"><span className="ui-row-title">#{g.id} {g.title}</span><span className="ui-row-meta">{g.objective}</span></span>
              </button>
              <span className="ui-row-end">
                <StatusPill tone={toneOf(g.status)}>{STATUS_VI[g.status] || g.status}</StatusPill>
                <span className="gl-progress" title={t("goals.tien_do", {p0: g.progress || 0})}><span className="ui-meter"><i style={{width: `${g.progress || 0}%`}}/></span></span>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => plan(g)}>{t("goals.lap_ke_hoach")}</Button>
                <Button size="sm" disabled={busy || !g.execution_plan_id} onClick={() => run(g)} title={g.execution_plan_id ? t("goals.chay_vong_van_hanh") : t("goals.can_lap_ke_hoach_truoc")}>{t("goals.chay")}</Button>
              </span>
            </div>)}</div>}
      </Panel>
      <div className="ui-grid">
        <Panel title={selected ? `#${selected.id} ${selected.title}` : t("goals.chon_mot_muc_tieu")} desc={selected ? t("goals.rui_ro", {p0: RISK_VI[selected.risk] || selected.risk, p1: selected.budget_limit != null ? ` · ngân sách $${selected.budget_limit}` : ""}) : t("goals.xem_viec_phuc_vu_muc")} testId="goal-tasks">
          {selected?.id ? <GoalTasks goalId={selected.id}/> : <p className="ui-empty-line">{t("goals.bam_vao_mot_muc_tieu")}</p>}
        </Panel>
        <Panel title={t("goals.vong_van_hanh_2")} desc={selected ? t("goals.cua_muc_tieu_dang_chon") : t("goals.gan_day")} flush>
          {shownCycles.length === 0 ? <p className="ui-empty-line" style={{padding: "12px 16px"}}>{t("goals.chua_co_vong_nao_lap")}</p>
            : <div className="ui-list">{shownCycles.map(c => <div key={c.id} className="ui-row">
                <span className="ui-row-main"><span className="ui-row-title">{t("goals.vong")}{c.id}</span><span className="ui-row-meta">{t("goals.muc_tieu_2")}{c.goal_id} {t("goals.che_do")} {c.mode}</span></span>
                <StatusPill tone={toneOf(c.status)}>{CYCLE_VI[c.status] || c.status}</StatusPill>
                <Button size="sm" variant="ghost" disabled={busy || ["completed", "cancelled"].includes(c.status)} onClick={() => tick(c)}>{t("goals.doi_soat")}</Button>
              </div>)}</div>}
        </Panel>
        <p className="ui-row-meta" style={{whiteSpace: "normal"}}>{t("goals.ke_hoach_theo_phong_ban")} <Link className="ui-link" href="/app/strategy">{t("goals.ke_hoach_cho_duyet")}</Link>.</p>
      </div>
    </div>

    {creating && <Dialog title={t("goals.muc_tieu_moi")} onClose={() => setCreating(false)} as="form" onSubmit={create} testId="goal-create-dialog"
      actions={<><Button onClick={() => setCreating(false)}>{t("goals.huy")}</Button><Button type="submit" variant="primary" busy={busy} disabled={!valid}>{t("goals.tao_muc_tieu")}</Button></>}>
      <Field label={t("goals.ten_muc_tieu")} hint={t("goals.ngan_gon_do_duoc")}><input value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder={t("goals.vd_ra_mat_bo_suu")} autoComplete="off" data-testid="goal-title"/></Field>
      <Field label={t("goals.ket_qua_muon_dat")} hint={t("goals.nina_dung_doan_nay_de")}><textarea rows={4} value={form.objective} onChange={e => setForm({...form, objective: e.target.value})} placeholder={t("goals.vd_200_don_dau_tien")}/></Field>
      <FormRow>
        <Field label={t("goals.cong_ty")}><select value={form.company_id} onChange={e => setForm({...form, company_id: e.target.value})}>
          <option value="">{t("goals.chon_cong_ty_thuc_hien")}</option>{companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label={t("goals.rui_ro_2")}><select value={form.risk} onChange={e => setForm({...form, risk: e.target.value})}>
          {Object.entries(RISK_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label={t("goals.ngan_sach_usd")}><input type="number" inputMode="decimal" min={0} value={form.budget} onChange={e => setForm({...form, budget: e.target.value})}/></Field>
      </FormRow>
    </Dialog>}
  </PageFrame>;
}
