"use client";
import {apiV14, apiV15} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Nina SRE (v15): phát hiện → lập kế hoạch → chính sách → duyệt → khôi phục, mọi quyết định được ghi lại. */
export function NinaSREV15Console() {
  const q = useLoad(async () => {
    const [summary, runs, decisions, routes, notes, nodes, incidents] = await Promise.all([apiV15.summary(), apiV15.sreRuns(), apiV15.sreDecisions(),
      apiV15.pagingRoutes(), apiV15.pagingNotifications(), apiV15.schedulerNodes(), apiV14.incidents()]);
    return {summary: summary as Any, runs: runs as Any[], decisions: decisions as Any[], routes: routes as Any[], notes: notes as Any[], nodes: nodes as Any[], incidents: incidents as Any[]};
  }, {summary: {}, runs: [], decisions: [], routes: [], notes: [], nodes: [], incidents: []});
  const {data, reload} = q;
  const act = useAction();
  const s = data.summary;
  const tick = () => act.run("tick", async () => { await apiV15.sreTick(); await apiV15.dispatchPaging(); await reload(); }, "Đã chạy một lượt SRE");
  return <LabBody q={q}>
    <Intro flow={["SLO / sự cố", "Nina lập kế hoạch", "Chính sách", "Duyệt", "Khôi phục"]}>
      Nina không có shell production tự do: cô lập kế hoạch khôi phục, đánh giá mức độ, dừng ở cổng duyệt khi rủi ro cao và ghi lại mọi quyết định.
      Lượt tự động (<code>v15.control_plane_tick</code>) chỉ chạy khi bật <code>LAB_JOBS_ENABLED</code>; nút dưới đây chạy một lượt bằng tay.
    </Intro>
    {act.error ? <ErrorBanner error={act.error} context="Chạy lượt SRE" onClose={() => act.setError(null)}/> : null}
    <Panel title="Vòng điều khiển" desc={`${s.open_incidents || 0} sự cố đang mở · ${s.sre_runs_active || 0} lượt khôi phục đang lập/chờ duyệt/chạy`}
      actions={<Button variant="primary" icon="pulse" busy={act.busy === "tick"} onClick={tick}>Chạy một lượt SRE</Button>}>
      <Stats items={[["Sự cố đang mở", s.open_incidents || 0], ["Lượt SRE đang chạy", s.sre_runs_active || 0], ["Tuyến báo động", s.paging_routes || 0], ["Nút lập lịch", s.scheduler_nodes_online || 0]]}/>
    </Panel>
    <div className="ui-grid is-2">
      <Panel title="Hàng đợi khôi phục" desc="Hành động tự động có cổng duyệt">
        <Table rows={data.runs.slice(0, 14)} empty="Chưa có lượt khôi phục nào." cols={[
          {label: "Lượt", render: x => <>#{x.id} · sự cố #{x.incident_id}</>, nowrap: true},
          {label: "Lần thử / duyệt", render: x => <small>lần {x.attempt} · {x.approval_id ? `duyệt #${x.approval_id}` : "không cần duyệt"}</small>, hideSm: true},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Quyết định của Nina" desc="Ý định SRE có giải thích">
        <Table rows={data.decisions.slice(0, 12)} empty="Chưa ghi quyết định SRE nào." cols={[
          {label: "Quyết định", render: x => <><b>{x.decision}</b><br/><small>{x.rationale}</small></>},
          {label: "Rủi ro", render: x => <Pill s={x.risk}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Báo động & độ sẵn sàng" desc={`${data.routes.length} tuyến · ${data.notes.length} thông báo · ${data.nodes.length} nút lập lịch`}>
      <Table rows={data.incidents.slice(0, 6)} empty="Không có sự cố nào đang hoạt động." cols={[
        {label: "Sự cố", render: x => <b>{x.title}</b>},
        {label: "Nguồn", render: x => x.source, hideSm: true},
        {label: "Mức độ", render: x => <Pill s={x.severity}/>},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
