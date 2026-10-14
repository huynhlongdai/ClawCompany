"use client";
import {useEffect} from "react";
import {apiV10} from "../lib/api";
import {viTime} from "../lib/labels";
import {Button} from "./ui/Button";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Buồng lái founder (v10): luồng sự kiện, tin nhắn agent, artifact, QA, SLA và vòng quyết định của Nina. Tự tải lại mỗi 15 giây. */
export function FounderCockpitV10() {
  const q = useLoad(async () => (await apiV10.founderCockpit()) as Any, {} as Any);
  useEffect(() => { const t = setInterval(q.reload, 15000); return () => clearInterval(t); }, [q.reload]);
  const d = q.data, m = d.metrics || {};
  return <LabBody q={q}>
    <Intro>Bus sự kiện gộp runtime, tin nhắn giữa agent, artifact, QA, SLA và vòng quyết định của Nina thành một luồng quan sát được. Tự tải lại mỗi 15 giây.</Intro>
    <Stats items={[["Sự kiện chờ", m.pending_events], ["Tin nhắn agent 24 giờ", m.messages_24h], ["Artifact sẵn sàng", m.ready_artifacts], ["QA cần sửa", m.qa_changes_requested],
      ["Vi phạm SLA", m.sla_breaches], ["Sự cố", m.open_recovery_incidents], ["Chờ duyệt", m.pending_approvals], ["Mục tiêu đang chạy", m.active_goals]].map(([a, b]) => [a, Number(b || 0).toLocaleString("vi-VN")])}/>
    <div className="ui-grid is-2">
      <Panel title="Luồng sự kiện công ty" desc="Sự kiện bền vững đang chờ hoặc đã được trigger xử lý"
        actions={<Button size="sm" icon="arrow-right" busy={q.loading} onClick={q.reload}>Tải lại</Button>}>
        <Table rows={d.events || []} empty="Chưa có sự kiện nào." cols={[
          {label: "Sự kiện", render: e => <><code>{e.event_type}</code><br/><small>{e.source} · #{e.id}</small></>}, {label: "Trạng thái", render: e => <Pill s={e.status}/>},
        ]}/>
      </Panel>
      <Panel title="Vòng quyết định liên tục của Nina" desc="Ảnh chụp tình hình và quyết định gần nhất">
        <Table rows={d.decision_runs || []} empty="Vòng quyết định chưa chạy lần nào." cols={[
          {label: "Lượt", render: r => <>#{r.id}<br/><small>{viTime(r.created_at)}</small></>, nowrap: true},
          {label: "Quyết định", render: r => (r.decisions || []).map((x: Any, i: number) => <div key={i}><code>{x.type}</code> {x.reason}</div>)},
        ]}/>
      </Panel>
    </div>
    <div className="ui-grid is-3">
      <Panel title="Artifact" desc="Mã nguồn, báo cáo, sản phẩm">
        <Table rows={(d.artifacts || []).slice(0, 7)} empty="Chưa có artifact." cols={[
          {label: "Tệp", render: x => <><b>{x.logical_path || x.name}</b><br/><small>{x.artifact_type} · v{x.version}</small></>}, {label: "", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Tin nhắn agent" desc="Uỷ quyền và bàn giao">
        <Table rows={(d.messages || []).slice(0, 7)} empty="Chưa có tin nhắn." cols={[
          {label: "Tin", render: x => <><b>{x.subject || x.message_type}</b><br/><small>{String(x.content || "").slice(0, 70)}</small></>}, {label: "", render: x => <Pill s={x.priority}/>},
        ]}/>
      </Panel>
      <Panel title="Chất lượng & SLA" desc="Việc cần founder/quản lý để ý">
        <Table rows={[...(d.sla_incidents || []).slice(0, 4).map((x: Any) => ({id: "s" + x.id, t: `SLA #${x.id}`, s: x.summary, st: x.status})),
          ...(d.evaluations || []).filter((x: Any) => x.verdict === "changes_requested").slice(0, 4).map((x: Any) => ({id: "q" + x.id, t: `Artifact #${x.artifact_id}`, s: `điểm QA ${x.score}`, st: x.verdict}))]}
          empty="Không có gì cần để ý." cols={[{label: "Mục", render: x => <><b>{x.t}</b><br/><small>{x.s}</small></>}, {label: "", render: x => <Pill s={x.st}/>}]}/>
      </Panel>
    </div>
  </LabBody>;
}
