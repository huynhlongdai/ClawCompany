"use client";
import {apiV14} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · SLO & đo lường (v14): mẫu đo theo tổ chức, SLO có ngưỡng + cửa sổ, lần đánh giá gần đây. */
export function ObservabilityConsole() {
  const q = useLoad(async () => {
    const [slos, evs, metrics] = await Promise.all([apiV14.slos(), apiV14.sloEvaluations(), apiV14.metrics()]);
    return {slos: slos as Any[], evs: evs as Any[], metrics: metrics as Any[]};
  }, {slos: [], evs: [], metrics: []});
  const {data, reload} = q;
  const latest = new Map<string, Any>();
  data.metrics.forEach(x => { if (!latest.has(x.metric_name)) latest.set(x.metric_name, x); });
  return <LabBody q={q}>
    <Intro flow={["Đo", "Đánh giá SLO", "Hành động (dừng canary / mở sự cố)"]}>
      Thăng cấp bản triển khai dựa trên sức khoẻ dịch vụ, không chỉ build xanh. Job đánh giá SLO chỉ chạy khi máy chủ bật <code>LAB_JOBS_ENABLED</code>.
    </Intro>
    <Stats items={latest.size ? Array.from(latest.values()).slice(0, 4).map(x => [x.metric_name, `${Number(x.value).toFixed(2)} ${x.unit || ""}`]) : [["Luồng số đo", "—", "Chưa có mẫu đo nào"]]}/>
    <div className="ui-grid is-2">
      <Panel title="Mục tiêu mức dịch vụ (SLO)" desc="Chính sách thăng cấp theo từng môi trường">
        <Table rows={data.slos} empty="Chưa định nghĩa SLO nào." cols={[
          {label: "Tên", render: x => <><b>{x.name}</b><br/><small>{x.metric_name} · {x.window_minutes} phút · tối thiểu {x.min_samples} mẫu</small></>},
          {label: "Ngưỡng", render: x => <code>{x.comparator} {x.threshold}</code>, nowrap: true},
          {label: "Trạng thái", render: x => <Pill s={x.enabled ? "active" : "off"}/>},
        ]}/>
      </Panel>
      <Panel title="Lần đánh giá gần đây" desc="Đạt, vi phạm hoặc thiếu dữ liệu">
        <Table rows={data.evs.slice(0, 12)} empty="Chưa có lần đánh giá SLO nào." cols={[
          {label: "SLO", render: x => <>SLO #{x.slo_id}</>, nowrap: true},
          {label: "Mẫu", render: x => x.sample_count, num: true},
          {label: "Trung bình", render: x => x.aggregate_value ?? "—", num: true},
          {label: "Kết quả", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
