"use client";
import {PageFrame} from "./shell/PageFrame";
import {apiV9} from "../lib/api";
import {Button} from "./ui/Button";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Trung tâm điều hành (v9): mục tiêu, uỷ quyền, rủi ro, duyệt, bộ nhớ, ngân sách trong một màn. */
export function ExecutiveControlCenter() {
  const q = useLoad(async () => (await apiV9.controlCenter()) as Any, {} as Any);
  const d = q.data, m = d.metrics || {};
  const usd = (v: unknown) => `$${Number(v || 0).toFixed(2)}`;
  return <PageFrame action={<Button icon="arrow-right" busy={q.loading && q.loaded} onClick={q.reload}>Tải lại</Button>}>
    <LabBody q={q}>
      <Intro>Nina lập kế hoạch và uỷ quyền; quản lý và agent thực thi qua runtime. Ngân sách, ngưỡng rủi ro và phê duyệt vẫn là các nút điều khiển tường minh.
        Chế độ tự chủ hiện tại: <b>{d.autonomy?.mode || "—"}</b>.</Intro>
      <Stats items={[["Mục tiêu đang chạy", m.active_goals || 0], ["Việc AI đang chạy", m.running_assignments || 0], ["Sự cố đang mở", m.open_incidents || 0],
        ["Chờ duyệt", m.pending_approvals || 0], ["Ghi nhớ tổ chức", m.memory_items || 0], ["Chi phí AI 24 giờ", usd(m.usage_cost_24h)]]}/>
      <div className="ui-grid is-2">
        <Panel title="Mục tiêu điều hành" desc="Mục tiêu công ty theo kết quả">
          <Table rows={d.goals || []} empty="Chưa có mục tiêu điều hành nào." cols={[
            {label: "Mục tiêu", render: g => <><b>{g.title}</b><br/><small>ưu tiên {g.priority}</small></>},
            {label: "Tiến độ", render: g => <span className="ui-meter" style={{display: "block", width: 90}}><i style={{width: `${g.progress || 0}%`}}/></span>},
            {label: "Trạng thái", render: g => <Pill s={g.status}/>},
          ]}/>
        </Panel>
        <Panel title="Cần chú ý" desc="Sự cố và điểm dừng quản trị">
          <Table rows={d.incidents || []} empty="Không có sự cố nào đang mở." cols={[
            {label: "Sự cố", render: x => <><code>{x.incident_type}</code><br/><small>{x.error || "Lượt thực thi cần chú ý"}</small></>},
            {label: "Mức độ", render: x => <Pill s={x.severity}/>}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
          ]}/>
        </Panel>
        <Panel title="Chu kỳ vận hành" desc="Nina → quản lý → nhân sự AI">
          <Table rows={d.cycles || []} empty="Chưa có chu kỳ nào." cols={[
            {label: "Chu kỳ", render: c => <>#{c.id} · mục tiêu #{c.goal_id}</>}, {label: "Chế độ", render: c => c.mode}, {label: "Trạng thái", render: c => <Pill s={c.status}/>},
          ]}/>
        </Panel>
        <Panel title="Hạn mức ngân sách" desc={`Giới hạn cứng trước việc tự động · đã chi ${usd(m.budget_spent)} / ${usd(m.budget_limit)}`}>
          <Table rows={d.budgets || []} empty="Chưa có hạn mức nào." cols={[
            {label: "Ngân sách", render: b => <><b>{b.name}</b><br/><small>còn {usd(b.remaining)} {b.currency}</small></>},
            {label: "Đã dùng", render: b => { const pct = b.limit ? Math.min(100, Math.round(((b.spent + b.reserved) / b.limit) * 100)) : 0;
              return <span className={"ui-meter" + (pct >= 90 ? " is-risk" : pct >= 70 ? " is-wait" : "")} style={{display: "block", width: 90}}><i style={{width: `${pct}%`}}/></span>; }},
          ]}/>
        </Panel>
      </div>
    </LabBody>
  </PageFrame>;
}
