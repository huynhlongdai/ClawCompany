"use client";
import {useEffect, useState} from "react";
import Link from "next/link";
import {api, apiV17, apiV33} from "../lib/api";
import {Icon} from "./Icon";

/* Chi tiết một agent — màn hình "Nina · Chief of Staff" trong bản thiết kế.

   Mọi khối đều có nguồn thật:
   - hồ sơ, model, tỉ lệ thành công, chi phí 30 ngày -> /api/v17/workspace/people
   - nhiệm vụ đang giữ                              -> /api/v17/workspace/tasks
   - trạng thái runtime, phiên mồ côi                -> /api/v33/members/{id}/runtime
   - kỹ năng                                         -> /api/skills

   Mẫu còn có biểu đồ sparkline "tỉ lệ thành công 30 ngày". Hệ thống chỉ lưu
   MỘT con số success_rate, không có chuỗi thời gian, nên không vẽ — thay bằng
   thanh so với mục tiêu, là thứ đo được. */

type Row = Record<string, any>;

export function AgentDetail({memberId}: {memberId: number}) {
  const [agents, setAgents] = useState<Row[]>([]);
  const [tasks, setTasks] = useState<Row[]>([]);
  const [runtime, setRuntime] = useState<Row | null>(null);
  const [skills, setSkills] = useState<Row[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [a, t] = await Promise.all([apiV17.people("agent"), apiV17.tasks()]);
        setAgents((a as Row[]) || []);
        setTasks(((t as Row[]) || []).filter(x => x.assignee_member_id === memberId));
      } catch (e: any) { setError(e?.message || "Không tải được agent"); }
      try { setRuntime(await apiV33.memberRuntime(memberId)); } catch { setRuntime(null); }
      try { setSkills((await api.skills() as Row[]) || []); } catch { setSkills([]); }
    })();
  }, [memberId]);

  const me = agents.find(a => a.id === memberId);
  if (error) return <div className="v8Error">{error}</div>;
  if (!me) return <div className="v8Empty">Đang tải hồ sơ agent…</div>;

  const agent = me.agent || {};
  const success = Number(agent.success_rate ?? 0);
  const pct = success <= 1 ? success * 100 : success;
  const done = tasks.filter(t => t.status === "done").length;

  return <div>
    {/* ---------- hồ sơ ---------- */}
    <section className="v14Hero" style={{gridTemplateColumns: "auto minmax(0,1fr) auto"}}>
      <span className="avatarLg" style={{width: 72, height: 72, fontSize: 24}}>
        {(me.name || "?").slice(0, 1).toUpperCase()}
      </span>
      <div>
        <h2 style={{fontSize: 28}}>{me.name}</h2>
        <p>{me.role || "—"}{me.company_name ? ` · ${me.company_name}` : ""}
          {me.department_name ? ` · ${me.department_name}` : ""}</p>
        <div className="heroActions" style={{marginTop: 12}}>
          <span className={`statusPill ${agent.lifecycle === "active" ? "" : "busy"}`}>
            {agent.lifecycle === "active" ? "đã bind gateway" : agent.lifecycle || "chưa bind"}
          </span>
          {agent.runtime_agent_id && <code>{agent.runtime_agent_id}</code>}
          {agent.model && <span className="tag blueTag">{agent.model}</span>}
        </div>
      </div>
      <div style={{display: "grid", gap: 8, justifyItems: "end"}}>
        <Link className="v8Ghost" href="/app/openclaw">Lõi OpenClaw →</Link>
        <Link className="v8Ghost" href="/app/live-runs">Phiên đang chạy →</Link>
      </div>
    </section>

    {/* ---------- số liệu ---------- */}
    <section className="v14Metrics" style={{gridTemplateColumns: "repeat(auto-fit,minmax(178px,1fr))"}}>
      <div className="metric">
        <div className="metricIcon"><Icon name="check" size={16}/></div>
        <label>Nhiệm vụ đang giữ</label><strong>{tasks.length}</strong>
      </div>
      <div className="metric">
        <div className="metricIcon"><Icon name="board" size={16}/></div>
        <label>Đã hoàn thành</label><strong>{done}</strong>
      </div>
      <div className="metric">
        <div className="metricIcon"><Icon name="chart" size={16}/></div>
        <label>Tỉ lệ thành công</label>
        <strong>{pct ? `${Math.round(pct)}%` : "—"}</strong>
        {!!pct && <div className="progress" style={{marginTop: 6}}>
          <span style={{width: `${Math.min(100, pct)}%`}}/>
        </div>}
      </div>
      <div className="metric">
        <div className="metricIcon"><Icon name="doc" size={16}/></div>
        <label>Chi phí 30 ngày</label>
        <strong>{agent.cost_30d !== undefined ? `$${agent.cost_30d}` : "—"}</strong>
      </div>
    </section>

    <section className="v13Split">
      {/* ---------- nhiệm vụ ---------- */}
      <div className="panel">
        <div className="panelHead">
          <div><b>Nhiệm vụ của agent này</b></div>
          <Link className="v8Ghost" href="/app/os?tab=tasks">Bảng việc →</Link>
        </div>
        <table className="dataTable">
          <thead><tr><th>Nhiệm vụ</th><th>Dự án</th><th>Ưu tiên</th><th>Trạng thái</th></tr></thead>
          <tbody>
            {tasks.map(t => <tr key={t.id}>
              <td>{t.title}</td><td>{t.project_name || "—"}</td><td>{t.priority}</td>
              <td><span className="tag orangeTag">{t.status}</span></td>
            </tr>)}
            {!tasks.length && <tr><td colSpan={4}>
              <div className="v8Empty">Chưa có nhiệm vụ nào được giao.</div></td></tr>}
          </tbody>
        </table>
      </div>

      <div style={{display: "grid", gap: 16}}>
        {/* ---------- runtime ---------- */}
        <div className="panel">
          <div className="panelHead"><div><b>Trạng thái runtime</b></div><small>v33</small></div>
          {runtime ? <>
            <div className="kv">
              <span>Ghế</span><b>{runtime.member_status}{runtime.member_is_archived ? " · đã lưu trữ" : ""}</b>
            </div>
            <div className="kv">
              <span>Phiên mồ côi</span>
              <b>{runtime.orphan_count ?? 0}{runtime.orphan_count ? " — không worker nào theo dõi" : ""}</b>
            </div>
            {!!(runtime.orphans || []).length && <table className="dataTable">
              <thead><tr><th>Việc</th><th>Session key</th><th>Lease</th></tr></thead>
              <tbody>{runtime.orphans.map((o: Row) => <tr key={o.task_id}>
                <td>{o.title}</td>
                <td><code>{o.session_key}</code></td>
                <td><span className={`tag ${o.lease_held ? "greenTag" : "redTag"}`}>
                  {o.lease_held ? "có giữ" : "không ai giữ"}</span></td>
              </tr>)}</tbody>
            </table>}
            {runtime.note && <small style={{display: "block", marginTop: 8}}>{runtime.note}</small>}
          </> : <div className="v8Empty">Không đọc được trạng thái runtime.</div>}
        </div>

        {/* ---------- kỹ năng ---------- */}
        <div className="panel">
          <div className="panelHead"><div><b>Kỹ năng khả dụng</b></div><small>/api/skills</small></div>
          <div className="ninaChips">
            {skills.map(s => <span key={s.id} className="tag blueTag" title={s.description}>
              {s.name} <small style={{marginLeft: 4}}>v{s.version}</small>
            </span>)}
            {!skills.length && <small>Chưa khai kỹ năng nào.</small>}
          </div>
          <small style={{display: "block", marginTop: 6}}>
            Bảng <code>skills</code> khai theo tổ chức, chưa gắn riêng cho từng agent —
            nên đây là kỹ năng khả dụng, không phải kỹ năng đã cấp.
          </small>
        </div>
      </div>
    </section>
  </div>;
}
