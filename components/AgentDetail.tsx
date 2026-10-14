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
import {t as tr, lazy} from "../lib/i18n";

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

const ST_VI: Record<string, string> = lazy(() => ({backlog: tr("agent.ton_dong"), todo: tr("agent.can_lam"), in_progress: tr("agent.dang_lam"), review: tr("agent.cho_duyet"), blocked: tr("agent.bi_chan"), done: "Xong", cancelled: tr("agent.da_huy")}));
const PRIO_VI: Record<string, string> = lazy(() => ({urgent: tr("agent.khan"), high: "Cao", medium: tr("agent.vua"), low: tr("agent.thap")}));
const LC_VI: Record<string, string> = lazy(() => ({active: tr("agent.dang_lam_viec"), paused: tr("agent.tam_dung"), retired: tr("agent.da_nghi"), detached: tr("agent.roi_gateway"), runtime_missing: tr("agent.cho_gateway")}));

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

  if (error) return <ErrorState error={error} onRetry={load} context={tr("agent.tai_ho_so_agent")}/>;
  if (!agents) return <SkeletonRows n={3} h={80}/>;
  const me = agents.find(a => a.id === memberId);
  if (!me) return <EmptyState mood="loi" title={tr("agent.khong_tim_thay_agent_nay")} action={<ButtonLink href="/app/team?tab=ai" variant="primary">{tr("agent.ve_danh_sach_agent")}</ButtonLink>}>
    {tr("agent.agent_co_the_da_nghi")}</EmptyState>;

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
        <p>{[me.role || tr("agent.nhan_su_ai"), me.company_name, me.department_name].filter(Boolean).join(" · ")}</p>
        <div className="ui-chips">
          <StatusPill tone={agent.lifecycle === "active" ? "ok" : agent.lifecycle ? "wait" : "neutral"}>{LC_VI[agent.lifecycle] || agent.lifecycle || tr("agent.chua_gan_gateway")}</StatusPill>
          {agent.runtime_agent_id && <StatusPill tone="outline" dot={false}><span translate="no">{agent.runtime_agent_id}</span></StatusPill>}
          {agent.model && <StatusPill tone="info" dot={false}><span translate="no">{agent.model}</span></StatusPill>}
        </div>
      </div>
      <div className="ag-links"><ButtonLink href={`/app/work?assignee=${memberId}`} size="sm" icon="check">{tr("agent.viec_cua_agent")}</ButtonLink>
        <ButtonLink href="/app/openclaw" size="sm" icon="gear">OpenClaw</ButtonLink></div>
    </section>

    <div className="oc-facts">
      <div><small>{tr("agent.viec_dang_giu")}</small><b className="ui-num">{open.length}</b></div>
      <div><small>{tr("agent.da_xong")}</small><b className="ui-num">{done}</b></div>
      <div><small>{tr("agent.ti_le_thanh_cong")}</small><b className="ui-num">{pct ? `${Math.round(pct)}%` : "—"}</b>
        {!!pct && <span className="ui-meter" style={{width: "100%"}}><i style={{width: `${Math.min(100, pct)}%`}}/></span>}</div>
      <div><small>{tr("agent.chi_phi_30_ngay")}</small><b className="ui-num">{agent.cost_30d !== undefined ? `$${agent.cost_30d}` : "—"}</b></div>
    </div>

    <div className="ui-grid is-side">
      <Panel title={tr("agent.viec_cua_agent_nay")} flush actions={<Link className="ui-link" href={`/app/work?assignee=${memberId}`}>{tr("agent.mo_trong_cong_viec")} <Icon name="chevron-right" size={12}/></Link>}>
        {tasks.length === 0 ? <EmptyState compact mood="ngu" title={tr("agent.chua_duoc_giao_viec_nao")}>{tr("agent.giao_viec_o_cong_viec")}</EmptyState>
          : <div className="ui-list">{tasks.slice(0, 20).map(t => <Link key={t.id} href={`/app/work?peek=${t.id}`} className="ui-row">
              <span className={"ui-sdot is-" + t.status}/>
              <span className="ui-row-main"><span className="ui-row-title">{t.title}</span><span className="ui-row-meta">{t.project_name || "—"} {tr("agent.uu_tien")} {PRIO_VI[t.priority] || t.priority}</span></span>
              <StatusPill tone={toneOf(t.status)}>{ST_VI[t.status] || t.status}</StatusPill></Link>)}</div>}
      </Panel>
      <div className="ui-grid">
        <Panel title={tr("agent.trang_thai_runtime")} desc={tr("agent.phien_openclaw_cua_ghe_nay")}>
          {runtime ? <div className="ui-grid" style={{gap: 10}}>
            <dl className="ui-kv"><dt>{tr("agent.ghe")}</dt><dd>{runtime.member_status}{runtime.member_is_archived ? tr("agent.da_luu_tru") : ""}</dd>
              <dt>{tr("agent.phien_mo_coi")}</dt><dd>{runtime.orphan_count ?? 0}{runtime.orphan_count ? tr("agent.khong_worker_nao_theo_doi") : ""}</dd></dl>
            {!!(runtime.orphans || []).length && <div className="ui-list">{runtime.orphans.map((o: Row) => <div key={o.task_id} className="ui-row" style={{padding: "8px 0"}}>
              <span className="ui-row-main"><span className="ui-row-title">{o.title}</span><span className="ui-row-meta" translate="no">{o.session_key}</span></span>
              <StatusPill tone={o.lease_held ? "ok" : "risk"}>{o.lease_held ? tr("agent.co_giu") : tr("agent.khong_ai_giu")}</StatusPill></div>)}</div>}
            {runtime.note && <small>{runtime.note}</small>}
          </div> : <p className="ui-empty-line">{tr("agent.khong_doc_duoc_trang_thai")}</p>}
        </Panel>
        <Panel title={tr("agent.ky_nang_kha_dung")} desc={tr("agent.khai_theo_to_chuc_chua")}>
          <div className="ui-chips">{skills.map(s => <StatusPill key={s.id} tone="info" dot={false} title={s.description}>{s.name} · v{s.version}</StatusPill>)}
            {!skills.length && <small>{tr("agent.chua_khai_ky_nang_nao")}</small>}</div>
        </Panel>
      </div>
    </div>
  </div>;
}
