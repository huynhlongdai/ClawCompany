"use client";
// D2.3 — Ngân sách ba nấc: phạm vi (công ty/phòng ban/seat/dự án/mục tiêu),
// cảnh báo ở warn_pct, hết hạn mức thì seat tạm dừng; mở lại chỉ qua override
// có lý do (ghi audit). Chi tiêu lấy từ sổ cái (đã quyết toán theo gateway),
// không từ ước lượng.
import {useEffect, useState} from "react";
import {AuthGate} from "./AuthGate";
import {V9AppShell} from "./V9AppShell";
import {api, apiV9, errorText} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";

const SCOPE_VI: Record<string, string> = {company: "Công ty", department: "Phòng ban", member: "Seat", project: "Dự án", goal: "Mục tiêu"};
const STATE_VI: Record<string, {label: string; color: string}> = {
  ok: {label: "Bình thường", color: "#16794c"},
  warned: {label: "Cảnh báo — chỉ việc critical", color: "#b26a00"},
  exhausted: {label: "Hết hạn mức — seat tạm dừng", color: "#b42318"},
};
const usd = (n: any, d = 4) => `$${Number(n || 0).toFixed(d)}`;

function Bar({b}: {b: any}) {
  const spent = Math.min(100, Number(b.pct || 0));
  const reserved = b.amount_limit ? Math.min(100 - spent, Number(b.amount_reserved || 0) / b.amount_limit * 100) : 0;
  const color = STATE_VI[b.threshold_state]?.color || "#16794c";
  return <div style={{position: "relative", height: 10, background: "#eef0f3", borderRadius: 6, overflow: "hidden", margin: "6px 0"}}>
    <i style={{position: "absolute", left: 0, top: 0, bottom: 0, width: `${spent}%`, background: color}}/>
    <i style={{position: "absolute", left: `${spent}%`, top: 0, bottom: 0, width: `${reserved}%`, background: color, opacity: .35}}/>
    <i title={`Cảnh báo ở ${b.warn_pct}%`} style={{position: "absolute", left: `${b.warn_pct}%`, top: -2, bottom: -2, width: 2, background: "#555"}}/>
  </div>;
}

function Table({title, rows}: {title: string; rows: any[]}) {
  return <div style={{marginTop: 10}}>
    <b style={{fontSize: 13}}>{title}</b>
    {rows.length ? <table style={{width: "100%", fontSize: 13, borderCollapse: "collapse"}}><tbody>
      {rows.map((r: any) => <tr key={r.name} style={{borderBottom: "1px solid #eee"}}>
        <td style={{padding: "4px 0"}}>{r.name}</td><td style={{textAlign: "right"}}>{usd(r.spent_usd)}</td></tr>)}
    </tbody></table> : <div className="v9Empty" style={{padding: 6}}>Chưa có chi tiêu.</div>}
  </div>;
}

export function BudgetsConsole() {
  const [data, setData] = useState<any>(null), [sel, setSel] = useState<number | null>(null), [detail, setDetail] = useState<any>(null);
  const [error, setError] = useState(""), [note, setNote] = useState("");
  const [members, setMembers] = useState<any[]>([]), [departments, setDepartments] = useState<any[]>([]), [projects, setProjects] = useState<any[]>([]);
  const [form, setForm] = useState<any>({name: "", scope_type: "member", scope_id: "", amount_limit: "1", warn_pct: "80"});
  const [ov, setOv] = useState<any>({reason: "", add_usd: "1"});

  async function load() {
    try { const d = await apiV9.budgetsOverview(); setData(d); if (sel == null && d.budgets[0]) setSel(d.budgets[0].id); }
    catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => {
    load();
    api.members().then((x: any) => setMembers(x || [])).catch(() => {});
    api.departments().then((x: any) => setDepartments(x || [])).catch(() => {});
    api.projects().then((x: any) => setProjects(x || [])).catch(() => {});
  }, []);
  useEffect(() => { if (sel != null) apiV9.budget(sel).then(setDetail).catch((e: any) => setError(errorText(e))); }, [sel, data]);

  const b = data?.budgets?.find((x: any) => x.id === sel);
  const options = form.scope_type === "member" ? members.filter((m: any) => m.member_type === "agent")
    : form.scope_type === "department" ? departments : form.scope_type === "project" ? projects : [];
  const nameOf = (x: any) => {
    const list = x.scope_type === "member" ? members : x.scope_type === "department" ? departments : x.scope_type === "project" ? projects : [];
    const hit = list.find((m: any) => m.id === x.scope_id);
    return hit ? (hit.name || hit.title) : (x.scope_id ? `#${x.scope_id}` : "toàn bộ");
  };

  async function create() {
    setError(""); setNote("");
    try {
      await apiV9.createBudget({organization_id: activeOrganizationId(), name: form.name, scope_type: form.scope_type,
        scope_id: form.scope_id ? Number(form.scope_id) : null, amount_limit: Number(form.amount_limit), warn_pct: Number(form.warn_pct)});
      setNote("Đã tạo phong bì."); setForm({...form, name: ""}); await load();
    } catch (e: any) { setError(errorText(e)); }
  }
  async function override() {
    if (!b) return;
    setError(""); setNote("");
    try {
      const r: any = await apiV9.overrideBudget(b.id, {reason: ov.reason, add_usd: Number(ov.add_usd)});
      setNote(`Đã nâng hạn mức lên ${usd(r.budget.amount_limit, 2)} — khôi phục ${r.restored_members.length} seat, ${r.restored_tasks.length} task, xếp lại ${r.requeued_wakeups.length} lượt. Đã ghi audit.`);
      setOv({reason: "", add_usd: "1"}); await load();
    } catch (e: any) { setError(errorText(e)); }
  }

  return <AuthGate><V9AppShell title="Ngân sách AI" subtitle="Giữ chỗ trước khi gửi việc cho agent · quyết toán theo số thật của gateway">
    {error && <div className="v8Error" data-testid="budget-error">{error}</div>}
    {note && <div className="v8Card" style={{padding: 10, marginBottom: 10, borderLeft: "3px solid #16794c"}} data-testid="budget-note">{note}</div>}
    <div className="v9Grid2">
      <section className="v8Card">
        <div className="v8CardHead"><div><b>Phong bì ngân sách</b><span>Hết hạn mức thì gateway không nhận lượt chạy mới</span></div></div>
        <div className="v9List">
          {(data?.budgets || []).map((x: any) => <button className="v9BudgetButton" key={x.id} onClick={() => setSel(x.id)} data-testid={`budget-${x.id}`}
            style={{display: "block", textAlign: "left", width: "100%", outline: x.id === sel ? "2px solid #4f46e5" : undefined}}>
            <div style={{display: "flex", justifyContent: "space-between", gap: 8}}>
              <b>{x.name}</b>
              <small style={{color: STATE_VI[x.threshold_state]?.color}}>{STATE_VI[x.threshold_state]?.label || x.threshold_state}</small>
            </div>
            <small>{SCOPE_VI[x.scope_type] || x.scope_type}: {nameOf(x)} · cảnh báo ở {x.warn_pct}%</small>
            <Bar b={x}/>
            <small>Đã tiêu {usd(x.amount_spent)} · đang giữ {usd(x.amount_reserved)} · hạn mức {usd(x.amount_limit, 2)} ({Number(x.pct).toFixed(1)}%)</small>
          </button>)}
          {data && !data.budgets.length && <div className="v9Empty">Chưa có phong bì nào.</div>}
        </div>
        <div className="v9Form" style={{marginTop: 12}}>
          <b>Tạo phong bì</b>
          <div className="v9FormRow">
            <label>Tên<input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="VD: Nina tháng 10"/></label>
            <label>Phạm vi<select value={form.scope_type} onChange={e => setForm({...form, scope_type: e.target.value, scope_id: ""})}>
              {Object.entries(SCOPE_VI).filter(([k]) => k !== "goal").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            {form.scope_type !== "company" && <label>Thuộc<select value={form.scope_id} onChange={e => setForm({...form, scope_id: e.target.value})}>
              <option value="">— chọn —</option>{options.map((o: any) => <option key={o.id} value={o.id}>{o.name || o.title}</option>)}</select></label>}
          </div>
          <div className="v9FormRow">
            <label>Hạn mức (USD)<input type="number" step="0.01" value={form.amount_limit} onChange={e => setForm({...form, amount_limit: e.target.value})}/></label>
            <label>Cảnh báo ở (%)<input type="number" value={form.warn_pct} onChange={e => setForm({...form, warn_pct: e.target.value})}/></label>
          </div>
          <button className="v8Primary" onClick={create} disabled={!form.name}>Tạo</button>
        </div>
      </section>
      <section className="v8Card">
        <div className="v8CardHead"><div><b>{b ? b.name : "Chọn một phong bì"}</b><span>Chi tiêu thật theo seat, task, dự án</span></div></div>
        {b ? <div data-testid="budget-detail">
          <div className="v9LedgerSummary">
            <span>Hạn mức<b>{usd(b.amount_limit, 2)}</b></span><span>Đang giữ<b>{usd(b.amount_reserved)}</b></span>
            <span>Đã tiêu<b>{usd(b.amount_spent)}</b></span><span>Còn lại<b>{usd(b.remaining)}</b></span>
          </div>
          <Table title="Theo seat" rows={b.spend.by_seat}/>
          <Table title="Theo task" rows={b.spend.by_task}/>
          <Table title="Theo dự án" rows={b.spend.by_project}/>
          <div className="v9Form" style={{marginTop: 12, borderTop: "1px solid #eee", paddingTop: 10}}>
            <b>Nâng hạn mức (override)</b>
            <small>Cần lý do; ghi vào nhật ký audit. Seat bị tạm dừng và task bị chặn vì phong bì này sẽ được khôi phục.</small>
            <div className="v9FormRow">
              <label>Thêm (USD)<input type="number" step="0.01" value={ov.add_usd} onChange={e => setOv({...ov, add_usd: e.target.value})}/></label>
              <label>Lý do<input value={ov.reason} onChange={e => setOv({...ov, reason: e.target.value})} placeholder="VD: duyệt thêm cho chiến dịch Q4" data-testid="override-reason"/></label>
            </div>
            <button className="v8Primary" onClick={override} disabled={ov.reason.trim().length < 3} data-testid="override-submit">Nâng hạn mức</button>
          </div>
          {detail && <div className="v9Ledger" style={{marginTop: 12}}>
            <b style={{fontSize: 13}}>Sổ cái</b>
            {detail.ledger.slice(0, 30).map((x: any) => <div className="v9LedgerRow" key={x.id}>
              <span>{({reserve: "giữ chỗ", spend: "tiêu", release: "trả lại", credit: "điều chỉnh giảm"} as any)[x.entry_type] || x.entry_type}</span>
              <b>{usd(x.amount)}</b><small>{x.source_id} · {x.memo}</small></div>)}
          </div>}
        </div> : <div className="v9Empty">Chọn một phong bì để xem chi tiêu.</div>}
      </section>
    </div>
    {data?.all && <section className="v8Card" style={{marginTop: 12}}>
      <div className="v8CardHead"><div><b>Toàn tổ chức</b><span>Mỗi lượt chạy chỉ đếm một lần dù nằm trong nhiều phong bì · tổng {usd(data.all.total_usd)}</span></div></div>
      <div className="v9Grid2"><Table title="Theo seat" rows={data.all.by_seat}/><Table title="Theo dự án" rows={data.all.by_project}/></div>
    </section>}
  </V9AppShell></AuthGate>;
}
