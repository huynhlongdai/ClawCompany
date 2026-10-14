"use client";
import {apiV13} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Quản lý phát hành (v13): chỉ thăng cấp khi CI, bảo mật, duyệt và sức khoẻ triển khai cùng đồng ý. */
export function ReleaseManagerV13Console() {
  const q = useLoad(async () => {
    const [d, s, h] = await Promise.all([apiV13.releaseManagerRuns(), apiV13.deploymentStrategies(), apiV13.healthRuns()]);
    return {decisions: d as Any[], strategies: s as Any[], health: h as Any[]};
  }, {decisions: [], strategies: [], health: []});
  const {data} = q;
  return <LabBody q={q}>
    <Intro>Quản lý phát hành hiện là dịch vụ quản trị xác định (chưa phải agent AI); sau này có thể bọc bằng agent mà không cho model vượt chính sách.
      Chiến lược: <b>cuốn chiếu</b> (triển khai → kiểm → rollback), <b>xanh/lam</b> (kiểm bản mới → chuyển một lần), <b>canary</b> (cần adapter router).</Intro>
    <div className="ui-grid is-2">
      <Panel title="Quyết định phát hành" desc="Duyệt / giữ / từ chối kèm bằng chứng">
        <Table rows={data.decisions} empty="Chưa có quyết định nào." cols={[
          {label: "Bản phát hành", render: x => <><b>#{x.release_id}</b><br/><small>{x.reason}</small></>},
          {label: "Quyết định", render: x => <Pill s={x.decision}/>},
        ]}/>
      </Panel>
      <Panel title="Triển khai dần" desc="Máy trạng thái của chiến lược">
        <Table rows={data.strategies} empty="Chưa chạy chiến lược triển khai nào." cols={[
          {label: "Chiến lược", render: x => <><code>{x.strategy}</code><br/><small>bản #{x.release_id} → môi trường #{x.environment_id}</small></>},
          {label: "Lưu lượng", render: x => `${x.traffic_percent}%`, num: true},
          {label: "Rollback", render: x => x.rollback_id ? `#${x.rollback_id}` : "Không", hideSm: true},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Kiểm tra sức khoẻ" desc="Kiểm sau triển khai, có móc rollback tự động">
      <Table rows={data.health.slice(0, 12)} empty="Chưa có lần kiểm tra sức khoẻ nào." cols={[
        {label: "Lần", render: x => <>#{x.id}</>}, {label: "Lượt triển khai", render: x => <>#{x.deployment_id}</>},
        {label: "Đạt / lỗi", render: x => `${x.successes} / ${x.failures}`, num: true}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
