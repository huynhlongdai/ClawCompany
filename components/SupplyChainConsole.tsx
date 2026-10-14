"use client";
import {apiV13} from "../lib/api";
import {Any, Intro, KV, LabBody, Panel, Pill, Table, short, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Chuỗi cung ứng phần mềm (v13): manifest nguồn, SBOM SPDX 2.3, provenance kiểu SLSA, review bảo mật. */
export function SupplyChainConsole() {
  const q = useLoad(async () => {
    const [b, r] = await Promise.all([apiV13.builds(), apiV13.securityReviews()]);
    return {builds: b as Any[], reviews: r as Any[]};
  }, {builds: [], reviews: []});
  const {data} = q;
  return <LabBody q={q}>
    <Intro flow={["Commit", "Manifest", "SBOM", "Provenance"]}>
      Mỗi bản phát hành giải thích được mã nguồn nào đã vào và cổng nào đã duyệt. Manifest, SPDX 2.3 JSON và provenance là artifact bất biến bình thường, review và bàn giao được như mã.
    </Intro>
    <div className="ui-grid is-2">
      <Panel title="Bằng chứng build">
        <Table rows={data.builds} empty="Chưa có bằng chứng build nào." cols={[
          {label: "Build", render: x => <>#{x.id}</>}, {label: "Commit", render: x => <code>{short(x.commit_sha, 14)}</code>},
          {label: "Digest nguồn", render: x => <code>{short(x.source_digest, 18)}…</code>, hideSm: true}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Review bảo mật" desc="Cổng phát hành đóng khi lỗi">
        <Table rows={data.reviews} empty="Chưa có review bảo mật nào." cols={[
          {label: "Review", render: x => <><b>#{x.id}</b><br/><small>{x.summary}</small></>},
          {label: "Điểm", render: x => Math.round(x.score || 0), num: true}, {label: "Kết luận", render: x => <Pill s={x.verdict}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Giới hạn của bộ quét">
      <KV items={[["Làm được", "Phát hiện mẫu mã rủi ro cao xác định: khoá riêng bị commit, gọi shell, giải tuần tự hoá không an toàn, tắt xác minh TLS."],
        ["Không khẳng định", "Không phải cơ sở dữ liệu CVE phụ thuộc, không thay SAST, không phải dịch vụ chứng thực chuỗi cung ứng chính thức — các việc đó là adapter cho bản triển khai đã gia cố."]]}/>
    </Panel>
  </LabBody>;
}
