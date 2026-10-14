"use client";
import {apiV12} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, short, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Dev Cloud (v12): workspace cô lập → sandbox có chính sách → commit bất biến → triển khai có duyệt. */
export function DevCloudConsole() {
  const q = useLoad(async () => (await apiV12.dashboard()) as Any, {} as Any);
  const d = q.data, m = d.metrics || {};
  return <LabBody q={q}>
    <Intro flow={["Agent", "Artifact", "Workspace", "Sandbox", "Giao hàng", "Phát hành", "Triển khai"]}>
      Mỗi agent viết mã làm việc trong workspace cô lập, sandbox theo chính sách (tắt mạng, root chỉ đọc, bỏ capability), commit phát hành bất biến và đường triển khai có duyệt.
      Bí mật chỉ là tham chiếu + quyền ngắn hạn, không bao giờ chép vào prompt. Job dọn workspace hết hạn chỉ chạy khi bật <code>LAB_JOBS_ENABLED</code>.
    </Intro>
    <Stats items={[["Workspace đang mở", m.active_workspaces], ["Sandbox đang chạy", m.sandbox_running], ["Bản sẵn sàng", m.releases_ready],
      ["Triển khai 24 giờ", m.deployments_24h], ["Môi trường xem trước", m.preview_environments], ["Tham chiếu bí mật", m.secret_references]]}/>
    <div className="ui-grid is-2">
      <Panel title="Lượt sandbox gần đây" desc="Trạng thái chạy và nguồn gốc">
        <Table rows={d.sandbox_runs || []} empty="Chưa có lượt sandbox nào." cols={[
          {label: "Lượt", render: x => <><b>#{x.id} · {x.purpose}</b><br/><small>workspace #{x.workspace_id} · hồ sơ #{x.profile_id}</small></>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Chuyến phát hành" desc="Commit Git bất biến → môi trường">
        <Table rows={d.releases || []} empty="Chưa có bản phát hành nào." cols={[
          {label: "Phiên bản", render: x => <b>{x.version}</b>},
          {label: "Commit", render: x => <code>{x.commit_sha ? short(x.commit_sha) : "chờ"}</code>},
          {label: "Repo", render: x => <>#{x.repository_id}</>, hideSm: true},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Hoạt động triển khai" desc="Production không phải “một nhánh nữa”: mỗi môi trường có cổng duyệt và dòng rollback">
      <Table rows={d.deployments || []} empty="Chưa có lượt triển khai nào." cols={[
        {label: "Lượt", render: x => <>#{x.id}</>}, {label: "Bản phát hành", render: x => <>#{x.release_id}</>},
        {label: "Môi trường", render: x => <>#{x.environment_id}</>}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
