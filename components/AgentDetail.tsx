"use client";
import {useEffect, useState} from "react";
import Link from "next/link";
import {api, apiV17, apiV33} from "../lib/api";
import {Icon} from "./Icon";
import {StatusPill, toneOf} from "./ui/StatusPill";
import {ButtonLink} from "./ui/Button";
import {Panel} from "./ui/Panel";
import {ErrorState, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";

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

const ST_VI: Record<string, string> = {backlog: "Tồn đọng", todo: "Cần làm", in_progress: "Đang làm", review: "Chờ duyệt", blocked: "Bị chặn", done: "Xong", cancelled: "Đã huỷ"};
const PRIO_VI: Record<string, string> = {urgent: "Khẩn", high: "Cao", medium: "Vừa", low: "Thấp"};
const LC_VI: Record<string, string> = {active: "Đang làm việc", paused: "Tạm dừng", retired: "Đã nghỉ", detached: "Rời gateway", runtime_missing: "Chờ gateway"};

export function AgentDetail({memberId}: {memberId: number}) {
  const [agents, setAgents] = useState<Row[] | null>(null);
  const [tasks, setTasks] = useState<Row[]>([]);
  const [runtime, setRuntime] = useState<Row | null>(null);
  const [skills, setSkills] = useState<Row[]>([]);
  const [error, setError] = useState<unknown>(null);

  const load = () => {
    /* bốn nguồn song song (trước v2: 2 song song rồi runtime rồi skills — 3 nhịp chờ) */
    setError(null);
    Promise.allSettled([apiV17.people("agent"), apiV17.tasks(), apiV33.memberRuntime(memberId), api.skills()]).then(([a, t, r, k]) => {
      if (a.status === "fulfilled") setAgents((a.value as Row[]) || []); else { setError(a.reason); setAgents([]); }
      if (t.status === "fulfilled") setTasks(((t.value as Row[]) || []).filter(x => x.assignee_member_id === memberId));
      setRuntime(r.status === "fulfilled" ? r.value as Row : null);
      setSkills(k.status === "fulfilled" ? (k.value as Row[]) || [] : []);
    });
  };
  useEffect(load, [memberId]);

  if (error) return <ErrorState error={error} onRetry={load} context="Tải hồ sơ agent"/>;
  if (!agents) return <SkeletonRows n={3} h={80}/>;
  const me = agents.find(a => a.id === memberId);
  if (!me) return <EmptyState mood="loi" title="Không tìm thấy agent này" action={<ButtonLink href="/app/team?tab=ai" variant="primary">Về danh sách agent</ButtonLink>}>
    Agent có thể đã nghỉ việc hoặc thuộc tổ chức khác.</EmptyState>;

  const agent = me.agent || {};
  const success = Number(agent.success_rate ?? 0);
  const pct = success <= 1 ? success * 100 : success;
  const done = tasks.filter(t => t.status === "done").length;
  const open = tasks.filter(t => !["done", "cancelled"].includes(t.status));

  return <div className="ag">
    <section className="ag-hero">
      <span className="ui-ava is-agent ag-ava" aria-hidden="true"><Icon name="sparkle" size={26} strokeWidth={1.8}/></span>
      <div className="ag-id">
        <h2>{me.name}</h2>
        <p>{[me.role || "Nhân sự AI", me.company_name, me.department_name].filter(Boolean).join(" · ")}</p>
        <div className="ui-chips">
          <StatusPill tone={agent.lifecycle === "active" ? "ok" : agent.lifecycle ? "wait" : "neutral"}>{LC_VI[agent.lifecycle] || agent.lifecycle || "Chưa gắn gateway"}</StatusPill>
          {agent.runtime_agent_id && <StatusPill tone="outline" dot={false}><span translate="no">{agent.runtime_agent_id}</span></StatusPill>}
          {agent.model && <StatusPill tone="info" dot={false}><span translate="no">{agent.model}</span></StatusPill>}
        </div>
      </div>
      <div className="ag-links"><ButtonLink href={`/app/work?assignee=${memberId}`} size="sm" icon="check">Việc của agent</ButtonLink>
        <ButtonLink href="/app/openclaw" size="sm" icon="gear">OpenClaw</ButtonLink></div>
    </section>

    <div className="oc-facts">
      <div><small>Việc đang giữ</small><b className="ui-num">{open.length}</b></div>
      <div><small>Đã xong</small><b className="ui-num">{done}</b></div>
      <div><small>Tỉ lệ thành công</small><b className="ui-num">{pct ? `${Math.round(pct)}%` : "—"}</b>
        {!!pct && <span className="ui-meter" style={{width: "100%"}}><i style={{width: `${Math.min(100, pct)}%`}}/></span>}</div>
      <div><small>Chi phí 30 ngày</small><b className="ui-num">{agent.cost_30d !== undefined ? `$${agent.cost_30d}` : "—"}</b></div>
    </div>

    <div className="ui-grid is-side">
      <Panel title="Việc của agent này" flush actions={<Link className="ui-link" href={`/app/work?assignee=${memberId}`}>Mở trong Công việc <Icon name="chevron-right" size={12}/></Link>}>
        {tasks.length === 0 ? <EmptyState compact mood="ngu" title="Chưa được giao việc nào">Giao việc ở Công việc — agent nhận ngay.</EmptyState>
          : <div className="ui-list">{tasks.slice(0, 20).map(t => <Link key={t.id} href={`/app/work?peek=${t.id}`} className="ui-row">
              <span className={"ui-sdot is-" + t.status}/>
              <span className="ui-row-main"><span className="ui-row-title">{t.title}</span><span className="ui-row-meta">{t.project_name || "—"} · ưu tiên {PRIO_VI[t.priority] || t.priority}</span></span>
              <StatusPill tone={toneOf(t.status)}>{ST_VI[t.status] || t.status}</StatusPill></Link>)}</div>}
      </Panel>
      <div className="ui-grid">
        <Panel title="Trạng thái runtime" desc="Phiên OpenClaw của ghế này">
          {runtime ? <div className="ui-grid" style={{gap: 10}}>
            <dl className="ui-kv"><dt>Ghế</dt><dd>{runtime.member_status}{runtime.member_is_archived ? " · đã lưu trữ" : ""}</dd>
              <dt>Phiên mồ côi</dt><dd>{runtime.orphan_count ?? 0}{runtime.orphan_count ? " — không worker nào theo dõi" : ""}</dd></dl>
            {!!(runtime.orphans || []).length && <div className="ui-list">{runtime.orphans.map((o: Row) => <div key={o.task_id} className="ui-row" style={{padding: "8px 0"}}>
              <span className="ui-row-main"><span className="ui-row-title">{o.title}</span><span className="ui-row-meta" translate="no">{o.session_key}</span></span>
              <StatusPill tone={o.lease_held ? "ok" : "risk"}>{o.lease_held ? "Có giữ" : "Không ai giữ"}</StatusPill></div>)}</div>}
            {runtime.note && <small>{runtime.note}</small>}
          </div> : <p className="ui-empty-line">Không đọc được trạng thái runtime — kiểm tra kết nối ở Cài đặt › OpenClaw.</p>}
        </Panel>
        <Panel title="Kỹ năng khả dụng" desc="Khai theo tổ chức, chưa gắn riêng từng agent (M5)">
          <div className="ui-chips">{skills.map(s => <StatusPill key={s.id} tone="info" dot={false} title={s.description}>{s.name} · v{s.version}</StatusPill>)}
            {!skills.length && <small>Chưa khai kỹ năng nào.</small>}</div>
        </Panel>
      </div>
    </div>
  </div>;
}
