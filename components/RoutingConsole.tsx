"use client";
// D3.1 — Định tuyến phòng ban: việc giao cho phòng → trưởng phòng được đánh
// thức (lý do "routed"), đọc nhân sự + hướng dẫn phòng, gọi company_task_assign
// kèm lý do. Trang này cho thấy phòng đang giữ việc gì và vì sao việc đã giao
// cho người đó (task.routed trong company_events).
import {useEffect, useState} from "react";
import {AuthGate} from "./AuthGate";
import {V9AppShell} from "./V9AppShell";
import {api, apiV18, errorText} from "../lib/api";

const EV_VI: Record<string, string> = {
  "task.routed_to_department": "Giao cho phòng",
  "routing.head_wake": "Đánh thức trưởng phòng",
  "task.routed": "Trưởng phòng giao việc",
  "routing.run_finished": "Kết thúc lượt định tuyến",
};
const RULE_VI: Record<string, string> = {
  task_reference: "việc được giao/tham chiếu → đánh thức",
  comment_without_mention: "comment không @ → đánh thức",
  mention_routes_directly: "comment có @ → người được @ tự nhận",
  self_triggered: "trưởng phòng tự gây ra → không đánh thức",
  dedup_pending: "đã có lượt chờ → gộp",
  no_head: "phòng chưa có trưởng phòng",
};

function evText(e: any, names: Record<number, string>) {
  const p = e.payload || {};
  if (e.type === "task.routed") return `→ ${names[p.to_member_id] || "#" + p.to_member_id}: “${p.reason}”` + (p.auto_pick ? ` (tự chọn: ${p.auto_pick})` : "");
  if (e.type === "routing.head_wake") return (RULE_VI[p.rule] || p.rule) + (p.cause ? ` · ${p.cause}` : "");
  if (e.type === "routing.run_finished") return p.assigned ? "đã giao xong" : `chưa giao được (${p.state || "?"})`;
  if (e.type === "task.routed_to_department") return p.reason || "";
  return "";
}

export function RoutingConsole() {
  const [departments, setDepartments] = useState<any[]>([]), [sel, setSel] = useState<number | null>(null);
  const [data, setData] = useState<any>(null), [guide, setGuide] = useState("");
  const [tasks, setTasks] = useState<any[]>([]), [pick, setPick] = useState(""), [why, setWhy] = useState("");
  const [error, setError] = useState(""), [note, setNote] = useState("");

  useEffect(() => {
    api.departments().then((x: any) => { setDepartments(x || []); if (x?.[0]) setSel(x[0].id); }).catch((e: any) => setError(errorText(e)));
    api.tasks().then((x: any) => setTasks((x || []).filter((t: any) => ["backlog", "todo", "blocked"].includes(t.status)))).catch(() => {});
  }, []);
  async function load(id = sel) {
    if (id == null) return;
    try { const d = await apiV18.departmentRouting(id); setData(d); setGuide(d.department.guide || ""); }
    catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => { load(); }, [sel]);

  const names: Record<number, string> = Object.fromEntries((data?.roster || []).map((m: any) => [m.id, m.name]));
  async function saveGuide() {
    setError(""); setNote("");
    try { await apiV18.setDepartmentGuide(sel!, guide); setNote("Đã lưu hướng dẫn phòng — lượt định tuyến sau sẽ đọc bản này."); await load(); }
    catch (e: any) { setError(errorText(e)); }
  }
  async function route() {
    setError(""); setNote("");
    try {
      const r: any = await apiV18.routeTask(Number(pick), sel!, why);
      const w = r.wake || {};
      setNote(`Đã giao task #${r.task_id} cho phòng. ${w.wake ? `Trưởng phòng được đánh thức (wakeup #${w.wakeup_id}).` : `Không đánh thức: ${RULE_VI[w.rule] || w.rule}.`}`);
      setPick(""); setWhy(""); await load();
    } catch (e: any) { setError(errorText(e)); }
  }

  const head = data?.department?.head;
  return <AuthGate><V9AppShell title="Định tuyến phòng ban" subtitle="Giao việc cho phòng · trưởng phòng chọn người, lý do ghi vào nhật ký sự kiện">
    {error && <div className="v8Error" data-testid="routing-error">{error}</div>}
    {note && <div className="v8Card" style={{padding: 10, marginBottom: 10, borderLeft: "3px solid #16794c"}} data-testid="routing-note">{note}</div>}
    <div style={{display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12}}>
      {departments.map((d: any) => <button key={d.id} className={d.id === sel ? "v8Primary" : "v8Ghost"} onClick={() => setSel(d.id)} data-testid={`dept-${d.id}`}>{d.name}</button>)}
      {!departments.length && <div className="v9Empty">Chưa có phòng ban nào.</div>}
    </div>
    {data && <div className="v9Grid2">
      <section className="v8Card">
        <div className="v8CardHead"><div><b>{data.department.name}</b>
          <span>Trưởng phòng: {head ? `${head.name}${head.type === "human" ? " (người — không tự định tuyến)" : ""}` : "chưa có — việc giao cho phòng sẽ không ai nhận"}</span></div></div>
        <b style={{fontSize: 13}}>Nhân sự phòng</b>
        <table style={{width: "100%", fontSize: 13, borderCollapse: "collapse", marginTop: 4}} data-testid="routing-roster"><tbody>
          {data.roster.map((m: any) => <tr key={m.id} style={{borderBottom: "1px solid #eee"}}>
            <td style={{padding: "4px 0"}}><b>{m.name}</b>{m.is_head && " · trưởng phòng"}<br/><small>{m.role || "chưa có mô tả vai"}</small></td>
            <td><small>{m.type === "agent" ? "AI" : "người"} · {m.status}</small></td>
            <td style={{textAlign: "right"}}><small>{m.open_tasks} việc mở · {m.open_runs} lượt chạy</small></td>
          </tr>)}
        </tbody></table>
        <div className="v9Form" style={{marginTop: 12}}>
          <b>Hướng dẫn phòng</b>
          <small>Trưởng phòng đọc phần này mỗi lượt định tuyến (mỗi dòng một quy tắc).</small>
          <textarea rows={5} value={guide} onChange={e => setGuide(e.target.value)} data-testid="routing-guide" style={{width: "100%"}}
            placeholder="VD: Bài SEO giao người viết nội dung; quảng cáo giao người chạy ads."/>
          <button className="v8Primary" onClick={saveGuide}>Lưu hướng dẫn</button>
        </div>
      </section>
      <section className="v8Card">
        <div className="v8CardHead"><div><b>Việc phòng đang giữ</b><span>Chưa có người nhận thì trưởng phòng sẽ định tuyến</span></div></div>
        <div className="v9List">
          {data.tasks.map((t: any) => <div key={t.id} className="v9BudgetButton" data-testid={`routing-task-${t.id}`}>
            <div style={{display: "flex", justifyContent: "space-between"}}><b>#{t.id} {t.title}</b><small>{t.status}</small></div>
            <small>{t.unassigned ? "⏳ chờ trưởng phòng giao" : `Người nhận: ${names[t.assignee_member_id] || "#" + t.assignee_member_id}`}</small>
            {data.events.filter((e: any) => e.task_id === t.id).slice(0, 4).map((e: any) => <div key={e.id} style={{fontSize: 12, color: "#555", marginTop: 2}}>
              · {EV_VI[e.type] || e.type}: {evText(e, names)}</div>)}
          </div>)}
          {!data.tasks.length && <div className="v9Empty">Phòng chưa giữ việc nào.</div>}
        </div>
        <div className="v9Form" style={{marginTop: 12}}>
          <b>Giao một việc cho phòng</b>
          <div className="v9FormRow">
            <label>Việc<select value={pick} onChange={e => setPick(e.target.value)} data-testid="routing-pick">
              <option value="">— chọn —</option>{tasks.map((t: any) => <option key={t.id} value={t.id}>#{t.id} {t.title}</option>)}</select></label>
            <label>Ghi chú<input value={why} onChange={e => setWhy(e.target.value)} placeholder="VD: việc nội dung cho chiến dịch"/></label>
          </div>
          <button className="v8Primary" onClick={route} disabled={!pick} data-testid="routing-submit">Giao cho phòng</button>
        </div>
      </section>
    </div>}
  </V9AppShell></AuthGate>;
}
