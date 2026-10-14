"use client";
import {apiV13} from "../lib/api";
import {ButtonLink} from "./ui/Button";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, short, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Tổ chức kỹ thuật (v13): Nina điều phối toàn bộ vòng đời phần mềm trên một mặt điều khiển. */
export function EngineeringOrgConsole() {
  const q = useLoad(async () => (await apiV13.dashboard()) as Any, {} as Any);
  const d = q.data, m = d.metrics || {};
  const rail = [...(d.ci_runs || []).slice(0, 4).map((x: Any) => ({id: "c" + x.id, k: `CI #${x.id}`, v: <code>{x.commit_sha ? short(x.commit_sha, 10) : "chờ"}</code>, s: x.status})),
    ...(d.security_reviews || []).slice(0, 3).map((x: Any) => ({id: "s" + x.id, k: `Bảo mật #${x.id}`, v: `${Math.round(x.score || 0)}/100`, s: x.verdict}))];
  return <LabBody q={q}>
    <Intro flow={["Ý tưởng / mục tiêu", "Sáng kiến của Nina", "Cổng workspace", "CI/CD", "Bảo mật + SBOM", "Quản lý phát hành", "Triển khai dần"]}>
      Phiên chat theo từng nhà cung cấp được chuyển thành phiên workspace có kiểm soát, bằng chứng bất biến, lượt CI/CD, cổng bảo mật và quyết định phát hành.
      Agent viết mã không cần chứng chỉ repository hay production. Nina chỉ đi tiếp khi cổng kế tiếp đã đạt.
    </Intro>
    <Stats items={[["Phiên gateway", m.gateway_sessions], ["Đồ thị pipeline", m.pipeline_graphs], ["CI đang chạy", m.ci_running], ["Bằng chứng build", m.builds],
      ["Bị chặn vì bảo mật", m.security_blocked], ["Phát hành bị giữ", m.release_holds], ["Sáng kiến đang chạy", m.initiatives_active]]}/>
    <div className="ui-grid is-2">
      <Panel title="Sáng kiến kỹ thuật của Nina" desc="Mục tiêu → đường phát hành có kiểm soát" actions={<ButtonLink href="/app/cicd" size="sm" icon="arrow-right">Mở CI/CD</ButtonLink>}>
        <Table rows={d.initiatives || []} empty="Chưa có sáng kiến kỹ thuật nào." cols={[
          {label: "Sáng kiến", render: x => <><b>{x.title}</b><br/><small>repo #{x.repository_id} · pipeline #{x.pipeline_graph_id}</small></>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Tình hình phát hành" desc="CI, bảo mật và triển khai mới nhất">
        <Table rows={rail} empty="Chưa có lượt CI hay review bảo mật nào." cols={[
          {label: "Mục", render: x => x.k, nowrap: true}, {label: "Giá trị", render: x => x.v}, {label: "Kết quả", render: x => <Pill s={x.s}/>},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
