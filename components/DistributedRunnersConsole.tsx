"use client";
import {apiV14} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, parseJson, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Runner phân tán (v14): cho agent thuê tài nguyên chạy mà không giao chứng chỉ hạ tầng. */
const PROVIDERS: [string, string, string][] = [
  ["Runner kéo việc từ xa", "Đã có", "Xác thực nút bằng API key + JWT workload gắn với lease"],
  ["Kubernetes", "Adapter", "Có hợp đồng lưu lượng + thực thi; chứng chỉ cụm nằm ngoài"],
  ["Firecracker / microVM", "Adapter", "Chỉ có hợp đồng broker; runner đặc quyền là hạ tầng riêng"],
  ["Tại chỗ", "Phát triển", "Không bao giờ là đường lùi ngầm cho nhà cung cấp production"],
];
export function DistributedRunnersConsole() {
  const q = useLoad(async () => {
    const [a, b, c] = await Promise.all([apiV14.runnerPools(), apiV14.runnerNodes(), apiV14.runnerLeases()]);
    return {pools: a as Any[], nodes: b as Any[], leases: c as Any[]};
  }, {pools: [], nodes: [], leases: []});
  const {data} = q;
  const online = data.nodes.filter(x => x.status === "online").length, active = data.leases.filter(x => x.status === "active").length;
  const free = data.nodes.reduce((n, x) => n + Math.max(0, (x.capacity || 0) - (x.active_leases || 0)), 0);
  return <LabBody q={q}>
    <Intro flow={["Agent", "Lease runner", "JWT workload", "Runner từ xa", "Kết quả"]}>
      Broker khớp năng lực và sức chứa, cấp danh tính workload ngắn hạn gắn với lease, rồi runner từ xa chỉ kéo đúng việc giao cho nút đó.
      Lease hết hạn thì danh tính bị thu hồi. Job dọn lease hết hạn chỉ chạy khi bật <code>LAB_JOBS_ENABLED</code>.
    </Intro>
    <Stats items={[["Nhóm runner", data.pools.length], ["Nút trực tuyến", online], ["Lease đang hiệu lực", active], ["Sức chứa còn trống", free]]}/>
    <div className="ui-grid is-2">
      <Panel title="Đội runner" desc="Nhịp tim + sức chứa + năng lực">
        <Table rows={data.nodes} empty="Chưa đăng ký runner từ xa nào." cols={[
          {label: "Nút", render: x => <><code>{x.node_key}</code><br/><small>{x.provider}</small></>},
          {label: "Đang dùng", render: x => `${x.active_leases}/${x.capacity}`, num: true},
          {label: "Năng lực", render: x => parseJson<string[]>(x.capabilities_json, []).join(", ") || "—", hideSm: true},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Lease" desc="Danh tính và việc chỉ sống trong đời của lease">
        <Table rows={data.leases.slice(0, 12)} empty="Chưa có lease nào." cols={[
          {label: "Lease", render: x => <>#{x.id}</>},
          {label: "Việc", render: x => <small>{x.workload_type} · {x.workload_ref || "chưa gắn"}</small>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Hợp đồng nhà cung cấp thực thi" desc="Mặt điều khiển hỗ trợ gì so với runtime thật có gì">
      <Table rows={PROVIDERS.map(([a, b, c]) => ({id: a, a, b, c}))} empty="" cols={[
        {label: "Nhà cung cấp", render: x => <b>{x.a}</b>},
        {label: "Mức", render: x => <Pill s={x.b === "Đã có" ? "ok" : "draft"} label={x.b}/>},
        {label: "Ghi chú", render: x => x.c},
      ]}/>
    </Panel>
  </LabBody>;
}
