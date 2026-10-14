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

/* Mục tiêu & Kế hoạch › Mục tiêu (v9 executive goals).
   Một mục tiêu đi qua: tạo → Nina lập kế hoạch (tạo việc con) → chạy vòng vận
   hành có cổng (rủi ro → duyệt, ngân sách mỗi lượt) → nhịp đối soát.
   UI v2: viết lại tiếng Việt trên primitive; hành vi API giữ nguyên. */

const STATUS_VI: Record<string, string> = {draft: "Mới tạo", planned: "Đã lập kế hoạch", plan_pending: "Kế hoạch chờ duyệt", plan_revision: "Nina đang sửa",
  plan_rejected: "Kế hoạch bị từ chối", active: "Đang chạy", running: "Đang chạy", completed: "Hoàn thành", cancelled: "Đã huỷ", blocked: "Bị chặn", waiting_approval: "Chờ duyệt"};
const RISK_VI: Record<string, string> = {low: "Thấp", medium: "Vừa", high: "Cao", critical: "Nghiêm trọng"};
const CYCLE_VI: Record<string, string> = {running: "Đang chạy", waiting_approval: "Chờ duyệt", completed: "Xong", failed: "Lỗi", cancelled: "Đã huỷ", blocked: "Bị chặn", queued: "Đang chờ"};

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
    if (g.status === "fulfilled") setGoals((g.value as any[]) || []); else { setLoadErr(g.reason); setGoals([]); }
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
      budget_limit: form.budget ? Number(form.budget) : null, currency: "USD"}), (x: any) => `Đã tạo mục tiêu #${x.id}`);
    if (g) { setSelected(g); setCreating(false); setForm(f => ({...f, title: "", objective: ""})); }
  }
  const plan = (g: any) => act(() => apiV9.planGoal(g.id, {max_steps: 5, project_id: null, auto_create_tasks: true}),
    (r: any) => { if (r?.goal?.id) setSelected(r.goal); return "Nina đã lập kế hoạch và tạo việc con"; });
  const run = (g: any) => act(() => apiV9.runGoal(g.id, {estimated_cost_per_assignment: 0.25, execute_unassigned: false}),
    (r: any) => `Vòng vận hành #${r?.cycle?.id}: ${CYCLE_VI[r?.cycle?.status] || r?.cycle?.status || "đã bắt đầu"}`);
  const tick = (c: any) => act(() => apiV9.tickCycle(c.id, true), () => `Đã đối soát vòng #${c.id}`);

  const shownCycles = useMemo(() => cycles.filter(c => !selected || c.goal_id === selected.id).slice(0, 12), [cycles, selected]);
  const valid = form.title.trim().length >= 2 && form.objective.trim().length >= 4;

  return <PageFrame action={<Button variant="primary" icon="plus" onClick={() => setCreating(true)} data-testid="goal-new">Mục tiêu mới</Button>}>
    {actErr ? <ErrorBanner error={actErr} onClose={() => setActErr(null)} context="Thao tác với mục tiêu"/> : null}
    <div className="ui-grid is-side">
      <Panel title="Mục tiêu" desc={goals ? `${goals.length} mục tiêu trong tổ chức` : "Đang tải…"} flush testId="goals-list">
        {loadErr ? <ErrorState error={loadErr} onRetry={load} context="Tải mục tiêu" compact/>
          : !goals ? <div className="ui-panel-body"><SkeletonRows n={4}/></div>
          : goals.length === 0 ? <EmptyState mood="chao" title="Chưa có mục tiêu" action={<Button variant="primary" onClick={() => setCreating(true)}>Đặt mục tiêu đầu tiên</Button>}>
              Đưa ra kết quả muốn đạt, không cần danh sách việc. Nina chia thành kế hoạch và giao cho đội.</EmptyState>
          : <div className="ui-list">{goals.map(g => <div key={g.id} className={"ui-row gl-row" + (selected?.id === g.id ? " is-on" : "")}>
              <button className="gl-pick" onClick={() => setSelected(g)} aria-pressed={selected?.id === g.id}>
                <span className="ui-row-main"><span className="ui-row-title">#{g.id} {g.title}</span><span className="ui-row-meta">{g.objective}</span></span>
              </button>
              <span className="ui-row-end">
                <StatusPill tone={toneOf(g.status)}>{STATUS_VI[g.status] || g.status}</StatusPill>
                <span className="gl-progress" title={`Tiến độ ${g.progress || 0}%`}><span className="ui-meter"><i style={{width: `${g.progress || 0}%`}}/></span></span>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => plan(g)}>Lập kế hoạch</Button>
                <Button size="sm" disabled={busy || !g.execution_plan_id} onClick={() => run(g)} title={g.execution_plan_id ? "Chạy vòng vận hành" : "Cần lập kế hoạch trước"}>Chạy</Button>
              </span>
            </div>)}</div>}
      </Panel>
      <div className="ui-grid">
        <Panel title={selected ? `#${selected.id} ${selected.title}` : "Chọn một mục tiêu"} desc={selected ? `Rủi ro ${RISK_VI[selected.risk] || selected.risk}${selected.budget_limit != null ? ` · ngân sách $${selected.budget_limit}` : ""}` : "Xem việc phục vụ mục tiêu và các vòng vận hành"} testId="goal-tasks">
          {selected?.id ? <GoalTasks goalId={selected.id}/> : <p className="ui-empty-line">Bấm vào một mục tiêu bên trái.</p>}
        </Panel>
        <Panel title="Vòng vận hành" desc={selected ? "Của mục tiêu đang chọn" : "Gần đây"} flush>
          {shownCycles.length === 0 ? <p className="ui-empty-line" style={{padding: "12px 16px"}}>Chưa có vòng nào. Lập kế hoạch rồi bấm Chạy.</p>
            : <div className="ui-list">{shownCycles.map(c => <div key={c.id} className="ui-row">
                <span className="ui-row-main"><span className="ui-row-title">Vòng #{c.id}</span><span className="ui-row-meta">Mục tiêu #{c.goal_id} · chế độ {c.mode}</span></span>
                <StatusPill tone={toneOf(c.status)}>{CYCLE_VI[c.status] || c.status}</StatusPill>
                <Button size="sm" variant="ghost" disabled={busy || ["completed", "cancelled"].includes(c.status)} onClick={() => tick(c)}>Đối soát</Button>
              </div>)}</div>}
        </Panel>
        <p className="ui-row-meta" style={{whiteSpace: "normal"}}>Kế hoạch theo phòng ban có duyệt/yêu cầu sửa nằm ở tab <Link className="ui-link" href="/app/strategy">Kế hoạch chờ duyệt</Link>.</p>
      </div>
    </div>

    {creating && <Dialog title="Mục tiêu mới" onClose={() => setCreating(false)} as="form" onSubmit={create} testId="goal-create-dialog"
      actions={<><Button onClick={() => setCreating(false)}>Huỷ</Button><Button type="submit" variant="primary" busy={busy} disabled={!valid}>Tạo mục tiêu</Button></>}>
      <Field label="Tên mục tiêu" hint="Ngắn gọn, đo được"><input value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder="VD: Ra mắt bộ sưu tập hè…" autoComplete="off" data-testid="goal-title"/></Field>
      <Field label="Kết quả muốn đạt" hint="Nina dùng đoạn này để chia việc"><textarea rows={4} value={form.objective} onChange={e => setForm({...form, objective: e.target.value})} placeholder="VD: 200 đơn đầu tiên trong 14 ngày, giữ chi phí quảng cáo dưới 5 triệu…"/></Field>
      <FormRow>
        <Field label="Công ty"><select value={form.company_id} onChange={e => setForm({...form, company_id: e.target.value})}>
          <option value="">Chọn công ty thực hiện</option>{companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="Rủi ro"><select value={form.risk} onChange={e => setForm({...form, risk: e.target.value})}>
          {Object.entries(RISK_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Ngân sách (USD)"><input type="number" inputMode="decimal" min={0} value={form.budget} onChange={e => setForm({...form, budget: e.target.value})}/></Field>
      </FormRow>
    </Dialog>}
  </PageFrame>;
}
