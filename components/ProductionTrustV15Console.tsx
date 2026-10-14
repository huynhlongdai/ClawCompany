"use client";
import {apiV15} from "../lib/api";
import {viTime} from "../lib/labels";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, short, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Tin cậy production (v15): danh tính runner mTLS, khoá ký workload xoay vòng, bằng chứng giao hàng có chữ ký. */
export function ProductionTrustV15Console() {
  const q = useLoad(async () => {
    const [summary, cas, certs, keys, policies, checks] = await Promise.all([apiV15.summary(), apiV15.trustAuthorities(), apiV15.runnerCertificates(),
      apiV15.workloadSigningKeys(), apiV15.evidencePolicies(), apiV15.evidenceVerifications()]);
    return {summary: summary as Any, cas: cas as Any[], certs: certs as Any[], keys: keys as Any[], policies: policies as Any[], checks: checks as Any[]};
  }, {summary: {}, cas: [], certs: [], keys: [], policies: [], checks: []});
  const {data, reload} = q; const s = data.summary;
  return <LabBody q={q}>
    <Intro flow={["Runner mTLS", "Lease", "JWT workload", "Bằng chứng có chữ ký"]}>
      Chứng chỉ hạ tầng dài hạn không bao giờ vào prompt agent. Chứng chỉ runner và token workload ngắn hạn, gắn với tổ chức, thu hồi riêng được.
      Nguyên tắc đóng khi lỗi: chứng chỉ hết hạn, khoá bị thu hồi hay bằng chứng không xác minh được thì dừng chạy, không âm thầm lùi về đường khác.
    </Intro>
    <Stats items={[["Chứng chỉ runner hiệu lực", s.runner_certificates_active || 0], ["Khoá workload hiệu lực", s.workload_keys_active || 0],
      ["Tổ chức cấp chứng chỉ", data.cas.length], ["Lần xác minh bằng chứng", data.checks.length]]}/>
    <div className="ui-grid is-2">
      <Panel title="Chứng chỉ runner" desc="Cấp từ tham chiếu CA do công ty quản lý">
        <Table rows={data.certs.slice(0, 12)} empty="Chưa cấp chứng chỉ runner nào." cols={[
          {label: "Nút", render: x => <>Runner #{x.runner_node_id}</>, nowrap: true},
          {label: "Dấu vân tay", render: x => <code>{short(x.fingerprint_sha256, 14)}…</code>, hideSm: true},
          {label: "Hết hạn", render: x => viTime(x.not_after), nowrap: true},
          {label: "Chuỗi", render: x => x.previous_certificate_id ? `xoay từ #${x.previous_certificate_id}` : "cấp gốc", hideSm: true},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Khoá ký workload" desc="Khoá đang dùng và khoá sắp nghỉ vẫn hiện trong JWKS tới khi bị thu hồi">
        <Table rows={data.keys.slice(0, 12)} empty="Đang dùng cấu hình v14 dự phòng cho tới khi tạo khoá ký có quản lý." cols={[
          {label: "Mã khoá", render: x => <><code>{x.kid}</code><br/><small>{x.algorithm} · {x.private_key_ref || "tham chiếu khoá ngoài"}</small></>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Chính sách tin cậy bằng chứng" desc="Xác minh chữ ký tách khỏi việc sinh artifact">
      <Table rows={data.policies} empty="Chưa có chính sách tin cậy production. HMAC chỉ dành cho môi trường phát triển; production nên ghim danh tính người ký bất đối xứng." cols={[
        {label: "Tên", render: x => <b>{x.name}</b>},
        {label: "Kiểu chữ ký", render: x => <code>{x.signature_type}</code>},
        {label: "Người ký", render: x => x.expected_signer || "ghim theo khoá", hideSm: true},
        {label: "Trạng thái", render: x => <Pill s={x.enabled ? "enabled" : "disabled"}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
