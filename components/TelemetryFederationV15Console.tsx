"use client";
import {apiV15} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Liên kết đo lường (v15): nhận OTLP JSON, xuất Prometheus, đẩy tới exporter trong danh sách cho phép. */
export function TelemetryFederationV15Console() {
  const q = useLoad(async () => {
    const [a, b] = await Promise.all([apiV15.telemetryExporters(), apiV15.summary()]);
    return {items: a as Any[], summary: b as Any};
  }, {items: [], summary: {}});
  const {data, reload} = q;
  return <LabBody q={q}>
    <Intro flow={["Ứng dụng", "OTLP JSON", "SLO ClawCompany", "Prometheus / OTLP"]}>
      Một mặt phẳng số đo cho ClawCompany, Prometheus và OTLP. Không có dữ liệu không có nghĩa là xanh: canary vẫn dừng khi thiếu số đo; lỗi xuất ghi riêng, không đổi kết quả SLO.
      Job xuất định kỳ chỉ chạy khi bật <code>LAB_JOBS_ENABLED</code>.
    </Intro>
    <Stats items={[["Exporter đã cấu hình", data.items.length], ["Exporter đang bật", data.summary.telemetry_exporters || 0],
      ["Sự cố đang mở", data.summary.open_incidents || 0], ["Điểm kéo số đo", <code key="u">/api/v15/metrics</code>]]}/>
    <Panel title="Exporter số đo" desc="Prometheus pull · Pushgateway · OTLP HTTP JSON">
      <Table rows={data.items} empty="Chưa có exporter nào. Prometheus pull đã có sẵn — chỉ tạo exporter khi cần đẩy đi." cols={[
        {label: "Tên", render: x => <b>{x.name}</b>},
        {label: "Nhà cung cấp", render: x => <code>{x.provider}</code>},
        {label: "Đích", render: x => x.endpoint ? <code>{x.endpoint}</code> : "Kéo từ ClawCompany", hideSm: true},
        {label: "Trạng thái", render: x => <Pill s={x.enabled ? "enabled" : "disabled"}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
