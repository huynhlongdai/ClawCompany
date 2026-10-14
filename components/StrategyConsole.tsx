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

const GOAL_VI: Record<string, string> = {draft: "mới tạo", plan_pending: "kế hoạch chờ duyệt", plan_revision: "Nina đang sửa kế hoạch",
  plan_rejected: "kế hoạch bị từ chối", active: "đang thực hiện", completed: "hoàn thành"};
const PLAN_VI: Record<string, string> = {pending: "chờ duyệt", revision_requested: "đã yêu cầu sửa", approved: "đã duyệt", rejected: "từ chối"};
const PLAN_TONE: Record<string, Tone> = {pending: "wait", revision_requested: "info", approved: "ok", rejected: "risk"};
const TASK_VI: Record<string, string> = {backlog: "Tồn đọng", todo: "Cần làm", in_progress: "Đang làm", review: "Chờ duyệt", blocked: "Bị chặn", done: "Xong", cancelled: "Đã huỷ"};

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
      toast(`Đã tạo mục tiêu #${g.id}. Nina được đánh thức để lập kế hoạch.`); setForm({...form, title: "", objective: ""});
      await load(); setSel(g.id);
    } catch (e2) { setError(e2); } finally { setBusy(false); }
  }

  const plan = view?.plans?.[0];
  return <PageFrame>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="strategy-error"/> : null}
    <div className="ui-grid is-side-l">
      <div className="ui-grid">
        <Panel title="Mục tiêu" desc={goals ? `${goals.length} mục tiêu` : "Đang tải…"} flush>
          {loadErr ? <ErrorState error={loadErr} onRetry={load} compact/> : !goals ? <div className="ui-panel-body"><SkeletonRows n={3}/></div>
            : goals.length === 0 ? <EmptyState compact mood="chao" title="Chưa có mục tiêu">Tạo mục tiêu bên dưới — Nina sẽ gửi kế hoạch để anh duyệt.</EmptyState>
            : <div className="ui-list">{goals.map((v: any) => { const p = v.plans[0];
              return <button key={v.goal.id} className="ui-row" onClick={() => setSel(v.goal.id)} aria-pressed={v.goal.id === sel} data-testid={`goal-${v.goal.id}`}
                style={v.goal.id === sel ? {background: "var(--selected)"} : undefined}>
                <span className="ui-row-main"><span className="ui-row-title">#{v.goal.id} {v.goal.title}</span>
                  <span className="ui-row-meta">{p ? `Kế hoạch bản ${p.revision} · ${p.tasks.length} việc` : v.planning_task ? `Chờ ${v.planning_task.assignee || "seat"} lập kế hoạch` : "Chưa có seat lập kế hoạch"}</span></span>
                {p ? <StatusPill tone={PLAN_TONE[p.status] || "neutral"}>{PLAN_VI[p.status] || p.status}</StatusPill> : <StatusPill tone="neutral">{GOAL_VI[v.goal.status] || v.goal.status}</StatusPill>}
              </button>; })}</div>}
        </Panel>
        <Panel title="Giao mục tiêu cho Nina" desc="Nina được đánh thức và gửi kế hoạch theo phòng ban">
          <form className="ui-form" onSubmit={createGoal}>
            <Field label="Mục tiêu"><input value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder="VD: Ra mắt bộ sưu tập hè…" data-testid="goal-title" autoComplete="off"/></Field>
            <Field label="Kết quả mong đợi"><textarea rows={3} value={form.objective} onChange={e => setForm({...form, objective: e.target.value})} placeholder="Mô tả mục tiêu, kết quả mong đợi…"/></Field>
            <FormRow>
              <Field label="Công ty"><select value={form.company_id} onChange={e => setForm({...form, company_id: e.target.value})}>
                {companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
              <Field label="Ngân sách (USD)"><input type="number" inputMode="decimal" min={0} value={form.budget} onChange={e => setForm({...form, budget: e.target.value})}/></Field>
            </FormRow>
            <Button type="submit" variant="primary" busy={busy} disabled={form.title.length < 2 || form.objective.length < 4} data-testid="goal-create">Giao cho Nina</Button>
          </form>
        </Panel>
      </div>

      <Panel title={view ? `#${view.goal.id} ${view.goal.title}` : "Kế hoạch"} testId="strategy-plan"
        desc={view ? `${GOAL_VI[view.goal.status] || view.goal.status}${view.goal.budget_usd != null ? ` · ngân sách $${view.goal.budget_usd.toFixed(2)}` : ""}` : "Chọn một mục tiêu"}>
        {!view ? <EmptyState compact mood="ngu" title="Chọn một mục tiêu">Kế hoạch Nina gửi sẽ hiện ở đây để anh duyệt.</EmptyState> : <div className="gl-plan">
          {!plan && <EmptyState compact mood={view.planning_task ? "lam-viec" : "loi"} title={view.planning_task ? "Nina đang lập kế hoạch" : "Chưa có seat lập kế hoạch"}>
            {view.planning_task ? `Việc lập kế hoạch #${view.planning_task.id} (${TASK_VI[view.planning_task.status] || view.planning_task.status}) — chờ ${view.planning_task.assignee} gửi kế hoạch.`
              : "Không có seat chiến lược (Nina) trong công ty này. Tuyển Nina ở Đội ngũ › Agent rồi tạo lại mục tiêu."}</EmptyState>}
          {plan && <>
            <div className="ui-toolbar"><b>Kế hoạch bản {plan.revision}</b><StatusPill tone={PLAN_TONE[plan.status] || "neutral"}>{PLAN_VI[plan.status] || plan.status}</StatusPill>
              {plan.approver && <span className="ui-row-meta">người duyệt: {plan.approver}</span>}</div>
            {plan.summary && <p className="gl-summary">{plan.summary}</p>}
            <ol className="gl-steps" data-testid="plan-tasks">{plan.tasks.map((t: any) => <li key={t.key}>
              <div><b>{t.title}</b>{t.acceptance_criteria && <small>Nghiệm thu: {t.acceptance_criteria}</small>}{t.depends_on.length > 0 && <small>Chờ: {t.depends_on.join(", ")}</small>}</div>
              <div style={{textAlign: "right"}}><small>{t.department_id ? `Phòng ${dept[t.department_id] || "#" + t.department_id}` : t.member_id ? (who[t.member_id] || "#" + t.member_id) : "Tự chọn theo tải"}</small>
                {t.budget_usd ? <small className="ui-num">${Number(t.budget_usd).toFixed(2)}</small> : null}</div>
            </li>)}</ol>
            {plan.status === "pending" && <div className="ui-form">
              <Field label="Ghi chú cho Nina" hint="Bắt buộc khi yêu cầu sửa (ít nhất 5 ký tự)"><textarea rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="VD: Gộp bước 2 và 3, giảm ngân sách quảng cáo…" data-testid="plan-note"/></Field>
              <div className="ui-confirm-actions">
                <Button variant="primary" busy={busy} onClick={() => act(() => apiInbox.resolveApproval(plan.approval_id, "approved", note), "Đã duyệt — việc con đã được tạo và giao.")} data-testid="plan-approve">Duyệt kế hoạch</Button>
                <Button disabled={busy || note.trim().length < 5} onClick={() => act(() => apiStrategy.requestRevision(plan.approval_id, note), "Đã gửi yêu cầu sửa — Nina được đánh thức.")} data-testid="plan-revise">Yêu cầu sửa</Button>
                <Button variant="danger" disabled={busy} onClick={() => act(() => apiInbox.resolveApproval(plan.approval_id, "rejected", note), "Đã từ chối kế hoạch.")}>Từ chối</Button>
              </div></div>}
            {plan.history.length > 0 && <div className="gl-history"><b>Các lần sửa</b>{plan.history.map((h: any) => <span key={h.revision}>Bản {h.revision} ({h.tasks} việc): “{h.note}”</span>)}</div>}
          </>}
          {view.tasks.length > 0 && <div><b style={{fontSize: 13}}>Việc đã giao</b>
            <div className="ui-list">{view.tasks.map((t: any) => <Link key={t.id} href={`/app/work?peek=${t.id}`} className="ui-row" data-testid={`goal-task-${t.id}`} style={{paddingLeft: 0, paddingRight: 0}}>
              <span className="ui-row-main"><span className="ui-row-title">#{t.id} {t.title}</span>
                <span className="ui-row-meta">{t.assignee ? t.assignee : t.department ? `Phòng ${t.department} — chờ trưởng phòng giao` : "Chưa có người nhận"}</span></span>
              <span className={"ui-sdot is-" + t.status}/><span className="ui-row-meta">{TASK_VI[t.status] || t.status}</span></Link>)}</div></div>}
        </div>}
      </Panel>
    </div>
  </PageFrame>;
}
