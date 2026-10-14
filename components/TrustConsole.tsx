"use client";
import {apiV14} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Table, short, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Tin cậy (v14): ký bằng chứng SBOM/provenance, adapter bộ quét, cổng trước khi thăng cấp bản phát hành. */
export function TrustConsole() {
  const q = useLoad(async () => {
    const [a, b, c] = await Promise.all([apiV14.signatures(), apiV14.scannerProviders(), apiV14.scannerRuns()]);
    return {sigs: a as Any[], providers: b as Any[], runs: c as Any[]};
  }, {sigs: [], providers: [], runs: []});
  const {data} = q;
  return <LabBody q={q}>
    <Intro flow={["Commit", "SBOM", "Provenance", "Chữ ký", "SAST / CVE", "Cổng phát hành"]}>
      SBOM và provenance là artifact bất biến, kèm bản ghi chữ ký; adapter bộ quét cho review xác định, Semgrep, Trivy, OSV Scanner.
      Không làm giả chứng thực: HMAC tại chỗ chỉ để phát triển; Cosign CLI là adapter tường minh; xác minh keyless vẫn bị chặn tới khi cấu hình chính sách tin cậy.
    </Intro>
    <div className="ui-grid is-2">
      <Panel title="Chữ ký bằng chứng" desc="Trạng thái xác minh gắn với digest">
        <Table rows={data.sigs} empty="Chưa có bằng chứng nào được ký." cols={[
          {label: "Artifact", render: x => <>#{x.artifact_id}</>},
          {label: "Digest", render: x => <code>{short(x.subject_digest, 20)}…</code>, hideSm: true},
          {label: "Kiểu", render: x => <code>{x.signature_type}</code>},
          {label: "Xác minh", render: x => <Pill s={x.verified ? "verified" : "unverified"}/>},
        ]}/>
      </Panel>
      <Panel title="Bộ quét" desc="Công cụ nào thật sự có">
        <Table rows={data.providers} empty="Chưa cấu hình bộ quét nào." cols={[
          {label: "Tên", render: x => <><b>{x.name}</b><br/><small>{x.provider_type} · chặn từ mức {x.block_on}</small></>},
          {label: "Trạng thái", render: x => <Pill s={x.enabled ? "enabled" : "off"}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Lượt quét ngoài" desc="Kết quả chuẩn hoá, không giấu lỗi của nhà cung cấp">
      <Table rows={data.runs} empty="Chưa có lượt quét nào." cols={[
        {label: "Lượt", render: x => <>#{x.id}</>},
        {label: "Bộ quét", render: x => <>#{x.provider_id}</>},
        {label: "Commit", render: x => <code>{short(x.commit_sha)}</code>},
        {label: "Kết luận", render: x => <Pill s={x.verdict}/>},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
