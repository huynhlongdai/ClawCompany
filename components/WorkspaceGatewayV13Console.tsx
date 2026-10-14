"use client";
import {apiV13} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Cổng workspace (v13): mọi nhà cung cấp agent dùng chung một giao thức workspace. */
export function WorkspaceGatewayV13Console() {
  const q = useLoad(async () => {
    const [a, b, c] = await Promise.all([apiV13.gatewaySessions(), apiV13.executionProviders(), apiV13.gatewayOperations()]);
    return {sessions: a as Any[], providers: b as Any[], ops: c as Any[]};
  }, {sessions: [], providers: [], ops: []});
  const {data} = q;
  return <LabBody q={q}>
    <Intro flow={["Agent của nhà cung cấp", "Phiên gateway", "Workspace phát triển", "Ảnh chụp artifact", "Agent commit"]}>
      Claude, Gemini, OpenClaw hay agent sau này dùng chung một giao thức. Phiên của nhà cung cấp không nhận chứng chỉ repository; chỉ có quyền đọc / ghi / chụp / đóng trong giới hạn, rồi giao mã nguồn cho kho artifact.
    </Intro>
    <div className="ui-grid is-2">
      <Panel title="Phiên gateway" desc="Danh tính + nhà cung cấp + lease workspace">
        <Table rows={data.sessions} empty="Chưa có phiên gateway nào." cols={[
          {label: "Phiên", render: x => <>#{x.id}</>}, {label: "Nhà cung cấp", render: x => <code>{x.provider}</code>},
          {label: "Workspace / thành viên", render: x => <small>#{x.workspace_id} · #{x.member_id || "—"}</small>, hideSm: true}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Lớp thực thi" desc="Hợp đồng cô lập của từng nhà cung cấp">
        <Table rows={data.providers.map(x => ({...x, id: x.provider}) as Any)} empty="Chưa có nhà cung cấp nào." cols={[
          {label: "Nhà cung cấp", render: x => <><b>{x.provider}</b><br/><small>{x.notes}</small></>},
          {label: "Cô lập", render: x => <code>{x.isolation}</code>},
          {label: "Mạng / bí mật", render: x => <small>{x.network_policy ? "Có chính sách mạng" : "Không chính sách mạng"} · {x.secrets_mount ? "gắn bí mật" : "không gắn bí mật"}</small>, hideSm: true},
        ]}/>
      </Panel>
    </div>
    <Panel title="Nhật ký thao tác workspace" desc="Mỗi lần đọc/ghi/chụp của nhà cung cấp thành một bản ghi lâu dài">
      <Table rows={data.ops.slice(0, 12)} empty="Chưa có thao tác nào." cols={[
        {label: "Phiên", render: x => <>#{x.session_id}</>}, {label: "Thao tác", render: x => <code>{x.operation_type}</code>},
        {label: "Đường dẫn", render: x => <code>{x.logical_path || "—"}</code>, hideSm: true}, {label: "Artifact", render: x => x.artifact_id ? `#${x.artifact_id}` : "—"},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
