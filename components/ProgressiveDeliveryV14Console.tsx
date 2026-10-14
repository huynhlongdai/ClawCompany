"use client";
import {apiV14} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Triển khai dần (v14): router lưu lượng + lịch sử từng bước canary có cổng SLO. */
export function ProgressiveDeliveryV14Console() {
  const q = useLoad(async () => {
    const [r, s] = await Promise.all([apiV14.trafficRouters(), apiV14.trafficShifts()]);
    return {routers: r as Any[], shifts: s as Any[]};
  }, {routers: [], shifts: []});
  const {data, reload} = q;
  return <LabBody q={q}>
    <Intro flow={["10%", "SLO", "25%", "SLO", "50%", "SLO", "100%"]}>
      Mỗi bước chuyển lưu lượng được ghi lại và chặn bởi SLO. Nhà cung cấp database/file chạy được tại chỗ; định tuyến Kubernetes Gateway API là adapter tuỳ chọn, mặc định tắt.
      SLO vi phạm → lưu lượng bản mới về 0% và mở sự cố.
    </Intro>
    <div className="ui-grid is-2">
      <Panel title="Router lưu lượng" desc="Trạng thái định tuyến theo môi trường">
        <Table rows={data.routers} empty="Chưa cấu hình router lưu lượng nào." cols={[
          {label: "Tên", render: x => <b>{x.name}</b>},
          {label: "Nhà cung cấp", render: x => <code>{x.provider}</code>},
          {label: "Trọng số hiện tại", render: x => <code>{x.current_weights_json || "{}"}</code>},
        ]}/>
      </Panel>
      <Panel title="Lịch sử chuyển lưu lượng" desc="Mỗi bước canary đều kiểm toán được">
        <Table rows={data.shifts.slice(0, 15)} empty="Chưa có lần chuyển lưu lượng nào." cols={[
          {label: "Bản phát hành", render: x => <>#{x.release_id} → <b>{x.to_weight}%</b></>, nowrap: true},
          {label: "Router / chiến lược", render: x => <small>router #{x.router_id} · {x.strategy_run_id ? `chiến lược #${x.strategy_run_id}` : "thủ công"}</small>, hideSm: true},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
