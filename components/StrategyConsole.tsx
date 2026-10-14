"use client";
// D3.3 — Kế hoạch mục tiêu: tạo mục tiêu → Nina được đánh thức (goal_created)
// và gửi kế hoạch (company_plan_submit) → người duyệt Duyệt / Yêu cầu sửa /
// Từ chối → duyệt xong hệ thống tạo việc con và giao cho phòng (trưởng phòng
// chọn người) hoặc seat. UI v2: cùng hành vi, viết lại trên primitive.
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiInbox, apiStrategy, apiV9} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill, Tone} from "./ui/StatusPill";
import {EmptyState, ErrorBanner, ErrorState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {t as tr, lazy} from "../lib/i18n";

const GOAL_VI: Record<string, string> = lazy(() => ({draft: tr("strategy.moi_tao"), plan_pending: tr("strategy.ke_hoach_cho_duyet"), plan_revision: tr("strategy.nina_dang_sua_ke_hoach"),
  plan_rejected: tr("strategy.ke_hoach_bi_tu_choi"), active: tr("strategy.dang_thuc_hien"), completed: tr("strategy.hoan_thanh")}));
const PLAN_VI: Record<string, string> = lazy(() => ({pending: tr("strategy.cho_duyet"), revision_requested: tr("strategy.da_yeu_cau_sua"), approved: tr("strategy.da_duyet"), rejected: tr("strategy.tu_choi")}));
const PLAN_TONE: Record<string, Tone> = {pending: "wait", revision_requested: "info", approved: "ok", rejected: "risk"};
const TASK_VI: Record<string, string> = lazy(() => ({backlog: tr("strategy.ton_dong"), todo: tr("strategy.can_lam"), in_progress: tr("strategy.dang_lam"), review: tr("strategy.cho_duyet_2"), blocked: tr("strategy.bi_chan"), done: "Xong", cancelled: tr("strategy.da_huy")}));

export function StrategyConsole() {
  const toast = useToast();
  const [goals, setGoals] = useState<any[] | null>(null), [sel, setSel] = useState<number | null>(null), [view, setView] = useState<any>(null);
  const [companies, setCompanies] = useState<any[]>([]), [departments, setDepartments] = useState<any[]>([]), [members, setMembers] = useState<any[]>([]);
  const [form, setForm] = useState({title: "", objective: "", budget: "20", company_id: ""});
  const [note, setNote] = useState(""), [loadErr, setLoadErr] = useState<unknown>(null), [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const d = await apiStrategy.goals(); setGoals(d.goals || []); setLoadErr(null); setSel(s => s ?? d.goals?.[0]?.goal.id ?? null); }
    catch (e) { setLoadErr(e); setGoals([]); }
  }, []);
  const open = useCallback(async (id: number | null) => { if (id != null) { try { setView(await apiStrategy.goal(id)); } catch (e) { setError(e); } } }, []);
  useEffect(() => {
    load();
    /* ba danh mục phụ — song song, lỗi thì chỉ mất tên hiển thị */
    Promise.allSettled([api.companies(activeOrganizationId()), api.departments(), api.members()]).then(([c, d, m]) => {
      if (c.status === "fulfilled") { const x: any = c.value || []; setCompanies(x); if (x[0]) setForm(f => ({...f, company_id: f.company_id || String(x[0].id)})); }
      if (d.status === "fulfilled") setDepartments((d.value as any) || []);
      if (m.status === "fulfilled") setMembers((m.value as any) || []);
    });
  }, [load]);
  useEffect(() => { open(sel); }, [sel, open]);
  const dept: Record<number, string> = Object.fromEntries(departments.map((d: any) => [d.id, d.name]));
  const who: Record<number, string> = Object.fromEntries(members.map((m: any) => [m.id, m.name]));

  async function act(fn: () => Promise<any>, ok: string) {
    setError(null); setBusy(true);
    try { await fn(); toast(ok); setNote(""); await load(); await open(sel); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function createGoal(e: React.FormEvent) {
    e.preventDefault(); setError(null); setBusy(true);
    try {
      const g: any = await apiV9.createGoal({organization_id: activeOrganizationId(), company_id: form.company_id ? Number(form.company_id) : null,
        title: form.title, objective: form.objective, budget_limit: form.budget ? Number(form.budget) : null, currency: "USD"});
      toast(tr("strategy.da_tao_muc_tieu_nina", {p0: g.id})); setForm({...form, title: "", objective: ""});
      await load(); setSel(g.id);
    } catch (e2) { setError(e2); } finally { setBusy(false); }
  }

  const plan = view?.plans?.[0];
  return <PageFrame>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="strategy-error"/> : null}
    <div className="ui-grid is-side-l">
      <div className="ui-grid">
        <Panel title={tr("strategy.muc_tieu")} desc={goals ? tr("strategy.muc_tieu_2", {p0: goals.length}) : tr("strategy.dang_tai")} flush>
          {loadErr ? <ErrorState error={loadErr} onRetry={load} compact/> : !goals ? <div className="ui-panel-body"><SkeletonRows n={3}/></div>
            : goals.length === 0 ? <EmptyState compact mood="chao" title={tr("strategy.chua_co_muc_tieu")}>{tr("strategy.tao_muc_tieu_ben_duoi")}</EmptyState>
            : <div className="ui-list">{goals.map((v: any) => { const p = v.plans[0];
              return <button key={v.goal.id} className="ui-row" onClick={() => setSel(v.goal.id)} aria-pressed={v.goal.id === sel} data-testid={`goal-${v.goal.id}`}
                style={v.goal.id === sel ? {background: "var(--selected)"} : undefined}>
                <span className="ui-row-main"><span className="ui-row-title">#{v.goal.id} {v.goal.title}</span>
                  <span className="ui-row-meta">{p ? tr("strategy.ke_hoach_ban_viec", {p0: p.revision, p1: p.tasks.length}) : v.planning_task ? tr("strategy.cho_lap_ke_hoach", {p0: v.planning_task.assignee || "seat"}) : tr("strategy.chua_co_seat_lap_ke")}</span></span>
                {p ? <StatusPill tone={PLAN_TONE[p.status] || "neutral"}>{PLAN_VI[p.status] || p.status}</StatusPill> : <StatusPill tone="neutral">{GOAL_VI[v.goal.status] || v.goal.status}</StatusPill>}
              </button>; })}</div>}
        </Panel>
        <Panel title={tr("strategy.giao_muc_tieu_cho_nina")} desc={tr("strategy.nina_duoc_danh_thuc_va")}>
          <form className="ui-form" onSubmit={createGoal}>
            <Field label={tr("strategy.muc_tieu")}><input value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder={tr("strategy.vd_ra_mat_bo_suu")} data-testid="goal-title" autoComplete="off"/></Field>
            <Field label={tr("strategy.ket_qua_mong_doi")}><textarea rows={3} value={form.objective} onChange={e => setForm({...form, objective: e.target.value})} placeholder={tr("strategy.mo_ta_muc_tieu_ket")}/></Field>
            <FormRow>
              <Field label={tr("strategy.cong_ty")}><select value={form.company_id} onChange={e => setForm({...form, company_id: e.target.value})}>
                {companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
              <Field label={tr("strategy.ngan_sach_usd")}><input type="number" inputMode="decimal" min={0} value={form.budget} onChange={e => setForm({...form, budget: e.target.value})}/></Field>
            </FormRow>
            <Button type="submit" variant="primary" busy={busy} disabled={form.title.length < 2 || form.objective.length < 4} data-testid="goal-create">Giao cho Nina</Button>
          </form>
        </Panel>
      </div>

      <Panel title={view ? `#${view.goal.id} ${view.goal.title}` : tr("strategy.ke_hoach")} testId="strategy-plan"
        desc={view ? `${GOAL_VI[view.goal.status] || view.goal.status}${view.goal.budget_usd != null ? tr("strategy.ngan_sach", {p0: view.goal.budget_usd.toFixed(2)}) : ""}` : tr("strategy.chon_mot_muc_tieu")}>
        {!view ? <EmptyState compact mood="ngu" title={tr("strategy.chon_mot_muc_tieu")}>{tr("strategy.ke_hoach_nina_gui_se")}</EmptyState> : <div className="gl-plan">
          {!plan && <EmptyState compact mood={view.planning_task ? "lam-viec" : "loi"} title={view.planning_task ? tr("strategy.nina_dang_lap_ke_hoach") : tr("strategy.chua_co_seat_lap_ke")}>
            {view.planning_task ? tr("strategy.viec_lap_ke_hoach_cho", {p0: view.planning_task.id, p1: TASK_VI[view.planning_task.status] || view.planning_task.status, p2: view.planning_task.assignee})
              : tr("strategy.khong_co_seat_chien_luoc")}</EmptyState>}
          {plan && <>
            <div className="ui-toolbar"><b>{tr("strategy.ke_hoach_ban")} {plan.revision}</b><StatusPill tone={PLAN_TONE[plan.status] || "neutral"}>{PLAN_VI[plan.status] || plan.status}</StatusPill>
              {plan.approver && <span className="ui-row-meta">{tr("strategy.nguoi_duyet")} {plan.approver}</span>}</div>
            {plan.summary && <p className="gl-summary">{plan.summary}</p>}
            <ol className="gl-steps" data-testid="plan-tasks">{plan.tasks.map((t: any) => <li key={t.key}>
              <div><b>{t.title}</b>{t.acceptance_criteria && <small>{tr("strategy.nghiem_thu")} {t.acceptance_criteria}</small>}{t.depends_on.length > 0 && <small>{tr("strategy.cho")} {t.depends_on.join(", ")}</small>}</div>
              <div style={{textAlign: "right"}}><small>{t.department_id ? tr("strategy.phong", {p0: dept[t.department_id] || "#" + t.department_id}) : t.member_id ? (who[t.member_id] || "#" + t.member_id) : tr("strategy.tu_chon_theo_tai")}</small>
                {t.budget_usd ? <small className="ui-num">${Number(t.budget_usd).toFixed(2)}</small> : null}</div>
            </li>)}</ol>
            {plan.status === "pending" && <div className="ui-form">
              <Field label={tr("strategy.ghi_chu_cho_nina")} hint={tr("strategy.bat_buoc_khi_yeu_cau")}><textarea rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder={tr("strategy.vd_gop_buoc_2_va")} data-testid="plan-note"/></Field>
              <div className="ui-confirm-actions">
                <Button variant="primary" busy={busy} onClick={() => act(() => apiInbox.resolveApproval(plan.approval_id, "approved", note), tr("strategy.da_duyet_viec_con_da"))} data-testid="plan-approve">{tr("strategy.duyet_ke_hoach")}</Button>
                <Button disabled={busy || note.trim().length < 5} onClick={() => act(() => apiStrategy.requestRevision(plan.approval_id, note), tr("strategy.da_gui_yeu_cau_sua"))} data-testid="plan-revise">{tr("strategy.yeu_cau_sua")}</Button>
                <Button variant="danger" disabled={busy} onClick={() => act(() => apiInbox.resolveApproval(plan.approval_id, "rejected", note), tr("strategy.da_tu_choi_ke_hoach"))}>{tr("strategy.tu_choi_2")}</Button>
              </div></div>}
            {plan.history.length > 0 && <div className="gl-history"><b>{tr("strategy.cac_lan_sua")}</b>{plan.history.map((h: any) => <span key={h.revision}>{tr("strategy.ban")} {h.revision} ({h.tasks} {tr("strategy.viec")}{h.note}”</span>)}</div>}
          </>}
          {view.tasks.length > 0 && <div><b style={{fontSize: 13}}>{tr("strategy.viec_da_giao")}</b>
            <div className="ui-list">{view.tasks.map((t: any) => <Link key={t.id} href={`/app/work?peek=${t.id}`} className="ui-row" data-testid={`goal-task-${t.id}`} style={{paddingLeft: 0, paddingRight: 0}}>
              <span className="ui-row-main"><span className="ui-row-title">#{t.id} {t.title}</span>
                <span className="ui-row-meta">{t.assignee ? t.assignee : t.department ? tr("strategy.phong_cho_truong_phong_giao", {p0: t.department}) : tr("strategy.chua_co_nguoi_nhan")}</span></span>
              <span className={"ui-sdot is-" + t.status}/><span className="ui-row-meta">{TASK_VI[t.status] || t.status}</span></Link>)}</div></div>}
        </div>}
      </Panel>
    </div>
  </PageFrame>;
}
