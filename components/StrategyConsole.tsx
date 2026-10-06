"use client";
// D3.3 — Kế hoạch mục tiêu: tạo mục tiêu → Nina được đánh thức (goal_created)
// và gửi kế hoạch (company_plan_submit) → người duyệt Duyệt / Yêu cầu sửa /
// Từ chối → duyệt xong hệ thống tạo việc con và giao cho phòng (trưởng phòng
// chọn người) hoặc seat.
import {useEffect, useState} from "react";
import {AuthGate} from "./AuthGate";
import {V9AppShell} from "./V9AppShell";
import {api, apiInbox, apiStrategy, apiV9, errorText} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";

const GOAL_VI: Record<string, string> = {draft: "mới tạo", plan_pending: "kế hoạch chờ duyệt", plan_revision: "Nina đang sửa kế hoạch",
  plan_rejected: "kế hoạch bị từ chối", active: "đang thực hiện"};
const PLAN_VI: Record<string, string> = {pending: "chờ duyệt", revision_requested: "đã yêu cầu sửa", approved: "đã duyệt", rejected: "từ chối"};

export function StrategyConsole() {
  const [goals, setGoals] = useState<any[]>([]), [sel, setSel] = useState<number | null>(null), [view, setView] = useState<any>(null);
  const [companies, setCompanies] = useState<any[]>([]), [departments, setDepartments] = useState<any[]>([]), [members, setMembers] = useState<any[]>([]);
  const [form, setForm] = useState({title: "", objective: "", budget: "20", company_id: ""});
  const [note, setNote] = useState(""), [msg, setMsg] = useState(""), [error, setError] = useState("");

  async function load() {
    try { const d = await apiStrategy.goals(); setGoals(d.goals || []); if (sel == null && d.goals?.[0]) setSel(d.goals[0].goal.id); }
    catch (e: any) { setError(errorText(e)); }
  }
  async function open(id = sel) { if (id != null) { try { setView(await apiStrategy.goal(id)); } catch (e: any) { setError(errorText(e)); } } }
  useEffect(() => {
    load();
    api.companies(activeOrganizationId()).then((x: any) => { setCompanies(x || []); if (x?.[0]) setForm(f => ({...f, company_id: String(x[0].id)})); }).catch(() => {});
    api.departments().then((x: any) => setDepartments(x || [])).catch(() => {});
    api.members().then((x: any) => setMembers(x || [])).catch(() => {});
  }, []);
  useEffect(() => { open(); }, [sel]);
  const dept: Record<number, string> = Object.fromEntries(departments.map((d: any) => [d.id, d.name]));
  const who: Record<number, string> = Object.fromEntries(members.map((m: any) => [m.id, m.name]));

  async function act(fn: () => Promise<any>, ok: string) {
    setError(""); setMsg("");
    try { await fn(); setMsg(ok); setNote(""); await load(); await open(); } catch (e: any) { setError(errorText(e)); }
  }
  async function createGoal() {
    setError(""); setMsg("");
    try {
      const g: any = await apiV9.createGoal({organization_id: activeOrganizationId(), company_id: form.company_id ? Number(form.company_id) : null,
        title: form.title, objective: form.objective, budget_limit: form.budget ? Number(form.budget) : null, currency: "USD"});
      setMsg(`Đã tạo mục tiêu #${g.id}. Nina được đánh thức để lập kế hoạch.`); setForm({...form, title: "", objective: ""});
      await load(); setSel(g.id);
    } catch (e: any) { setError(errorText(e)); }
  }

  const plan = view?.plans?.[0];
  return <AuthGate><V9AppShell title="Kế hoạch mục tiêu" subtitle="Nina phân rã mục tiêu thành việc cho từng phòng · bạn duyệt, yêu cầu sửa hoặc từ chối">
    {error && <div className="v8Error" data-testid="strategy-error">{error}</div>}
    {msg && <div className="v8Card" style={{padding: 10, marginBottom: 10, borderLeft: "3px solid #16794c"}} data-testid="strategy-note">{msg}</div>}
    <div className="v9Grid2">
      <section className="v8Card">
        <div className="v8CardHead"><div><b>Mục tiêu</b><span>{goals.length} mục tiêu</span></div></div>
        <div className="v9List">
          {goals.map((v: any) => <button key={v.goal.id} className="v9BudgetButton" onClick={() => setSel(v.goal.id)} data-testid={`goal-${v.goal.id}`}
            style={{textAlign: "left", outline: v.goal.id === sel ? "2px solid #1f5fbf" : undefined}}>
            <div style={{display: "flex", justifyContent: "space-between"}}><b>#{v.goal.id} {v.goal.title}</b><small>{GOAL_VI[v.goal.status] || v.goal.status}</small></div>
            <small>{v.plans[0] ? `Kế hoạch rev ${v.plans[0].revision} · ${PLAN_VI[v.plans[0].status] || v.plans[0].status} · ${v.plans[0].tasks.length} việc` : (v.planning_task ? `Chờ ${v.planning_task.assignee || "seat"} lập kế hoạch` : "Chưa có seat lập kế hoạch")}</small>
          </button>)}
          {!goals.length && <div className="v9Empty">Chưa có mục tiêu.</div>}
        </div>
        <div className="v9Form" style={{marginTop: 12}}>
          <b>Mục tiêu mới</b>
          <input value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder="VD: Ra mắt bộ sưu tập hè" data-testid="goal-title"/>
          <textarea rows={3} value={form.objective} onChange={e => setForm({...form, objective: e.target.value})} placeholder="Mô tả mục tiêu, kết quả mong đợi" style={{width: "100%"}}/>
          <div className="v9FormRow">
            <label>Công ty<select value={form.company_id} onChange={e => setForm({...form, company_id: e.target.value})}>
              {companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
            <label>Ngân sách (USD)<input type="number" min={0} value={form.budget} onChange={e => setForm({...form, budget: e.target.value})}/></label>
          </div>
          <button className="v8Primary" onClick={createGoal} disabled={form.title.length < 2 || form.objective.length < 4} data-testid="goal-create">Tạo mục tiêu</button>
        </div>
      </section>
      <section className="v8Card">
        {!view ? <div className="v9Empty">Chọn một mục tiêu.</div> : <>
          <div className="v8CardHead"><div><b>#{view.goal.id} {view.goal.title}</b>
            <span>{GOAL_VI[view.goal.status] || view.goal.status}{view.goal.budget_usd != null ? ` · ngân sách $${view.goal.budget_usd.toFixed(2)}` : ""}</span></div></div>
          {!plan && <div className="v9Empty">{view.planning_task ? `Việc lập kế hoạch #${view.planning_task.id} (${view.planning_task.status}) — chờ ${view.planning_task.assignee} gửi kế hoạch.` : "Không có seat chiến lược (Nina) để lập kế hoạch."}</div>}
          {plan && <>
            <div style={{fontSize: 13, marginBottom: 6}}><b>Kế hoạch rev {plan.revision}</b> · {PLAN_VI[plan.status] || plan.status}{plan.approver ? ` · người duyệt: ${plan.approver}` : ""}</div>
            <div style={{fontSize: 13, background: "#fafafa", padding: 8, borderRadius: 6, marginBottom: 8}}>{plan.summary}</div>
            <table style={{width: "100%", fontSize: 12, borderCollapse: "collapse"}} data-testid="plan-tasks"><tbody>
              {plan.tasks.map((t: any) => <tr key={t.key} style={{borderBottom: "1px solid #eee", verticalAlign: "top"}}>
                <td style={{padding: "4px 0"}}><b>{t.title}</b><br/><small>✔ {t.acceptance_criteria}</small>{t.depends_on.length > 0 && <><br/><small>chờ: {t.depends_on.join(", ")}</small></>}</td>
                <td><small>{t.department_id ? `phòng ${dept[t.department_id] || "#" + t.department_id}` : t.member_id ? (who[t.member_id] || "#" + t.member_id) : "tự chọn theo tải"}</small></td>
                <td style={{textAlign: "right"}}><small>{t.budget_usd ? `$${Number(t.budget_usd).toFixed(2)}` : ""}</small></td>
              </tr>)}
            </tbody></table>
            {plan.status === "pending" && <div className="v9Form" style={{marginTop: 10}}>
              <textarea rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="Ghi chú (bắt buộc khi yêu cầu sửa)" style={{width: "100%"}} data-testid="plan-note"/>
              <div style={{display: "flex", gap: 6}}>
                <button className="v8Primary" onClick={() => act(() => apiInbox.resolveApproval(plan.approval_id, "approved", note), "Đã duyệt — việc con đã được tạo và giao.")} data-testid="plan-approve">Duyệt</button>
                <button className="v8Ghost" disabled={note.trim().length < 5} onClick={() => act(() => apiStrategy.requestRevision(plan.approval_id, note), "Đã gửi yêu cầu sửa — Nina được đánh thức.")} data-testid="plan-revise">Yêu cầu sửa</button>
                <button className="v8Ghost" onClick={() => act(() => apiInbox.resolveApproval(plan.approval_id, "rejected", note), "Đã từ chối kế hoạch.")}>Từ chối</button>
              </div></div>}
            {plan.history.length > 0 && <div style={{fontSize: 12, color: "#555", marginTop: 8}}><b>Các lần sửa</b>
              {plan.history.map((h: any) => <div key={h.revision}>· rev {h.revision} ({h.tasks} việc): “{h.note}”</div>)}</div>}
          </>}
          {view.tasks.length > 0 && <><b style={{fontSize: 13, display: "block", marginTop: 12}}>Việc đã giao</b>
            <div className="v9List">{view.tasks.map((t: any) => <a key={t.id} href={`/app/tasks/${t.id}`} className="v9BudgetButton" data-testid={`goal-task-${t.id}`}>
              <div style={{display: "flex", justifyContent: "space-between"}}><b>#{t.id} {t.title}</b><small>{t.status}</small></div>
              <small>{t.assignee ? t.assignee : t.department ? `phòng ${t.department} — chờ trưởng phòng giao` : "chưa có người nhận"}</small></a>)}</div></>}
        </>}
      </section>
    </div>
  </V9AppShell></AuthGate>;
}
