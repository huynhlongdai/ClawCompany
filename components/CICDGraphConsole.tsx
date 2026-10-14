"use client";
import {apiV13} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Table, short, useLoad} from "./lab/kit";

const NODE_TYPES: [string, string][] = [["sandbox", "Chạy lệnh trong môi trường cô lập"], ["security", "Review bảo mật mã nguồn xác định"], ["evidence", "SPDX + provenance kiểu SLSA"],
  ["gate", "Quyết định quản trị đúng/sai"], ["release", "Tạo bản phát hành bất biến"], ["noop", "Ranh giới điều phối"]];

/* Phòng thí nghiệm · CI/CD (v13): đồ thị cổng ghép được thay cho một pipeline khổng lồ khó đọc. */
export function CICDGraphConsole() {
  const q = useLoad(async () => {
    const [g, r] = await Promise.all([apiV13.graphs(), apiV13.ciRuns()]);
    return {graphs: g as Any[], runs: r as Any[]};
  }, {graphs: [], runs: []});
  const {data} = q;
  return <LabBody q={q}>
    <Intro flow={["Nguồn · commit Git", "Sandbox · test + lint", "Bằng chứng · SBOM + provenance", "Bảo mật · cổng chính sách", "Phát hành · SHA bất biến"]}>
      Mỗi nút trong đồ thị kiểm toán được và có thể là một job sandbox, review bảo mật, sinh bằng chứng, thao tác phát hành hoặc cổng quản trị.
    </Intro>
    <div className="ui-grid is-2">
      <Panel title="Đồ thị pipeline" desc="Định nghĩa DAG có phiên bản">
        <Table rows={data.graphs} empty="Chưa có đồ thị pipeline nào." cols={[
          {label: "Đồ thị", render: x => <><b>{x.name}</b><br/><small>#{x.id} · repo #{x.repository_id} · v{x.version}</small></>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Lượt CI gần đây" desc="Chạy ghim theo commit">
        <Table rows={data.runs.slice(0, 10)} empty="Chưa có lượt CI nào." cols={[
          {label: "Lượt", render: x => <>#{x.id}</>}, {label: "Commit", render: x => <code>{x.commit_sha ? short(x.commit_sha) : "chờ"}</code>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Hợp đồng các loại nút" desc="Mọi loại nút đều có ngữ nghĩa rõ ở mặt điều khiển">
      <Table rows={NODE_TYPES.map(([a, b]) => ({id: a, a, b}))} empty="" cols={[{label: "Loại", render: x => <code>{x.a}</code>}, {label: "Làm gì", render: x => x.b}]}/>
    </Panel>
  </LabBody>;
}
