"use client";
import {apiV15} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Liên kết bí mật (v15): agent nhận "lease" để dùng bí mật, không bao giờ nhận giá trị làm bộ nhớ công ty. */
export function SecretsFederationV15Console() {
  const q = useLoad(async () => {
    const [a, b] = await Promise.all([apiV15.secretProviders(), apiV15.secretAccessLeases()]);
    return {providers: a as Any[], leases: b as Any[]};
  }, {providers: [], leases: []});
  const {data, reload} = q;
  const {providers, leases} = data;
  return <LabBody q={q}>
    <Intro flow={["Agent", "Quyền dùng bí mật", "Lease truy cập", "Nhà cung cấp", "Gắn tạm thời"]}>
      Chỉ lưu metadata: giá trị bí mật được lấy lúc thực thi từ biến môi trường, Vault hoặc CLI đám mây, và không bao giờ ghi vào cơ sở dữ liệu ClawCompany.
    </Intro>
    <Stats items={[["Nhà cung cấp", providers.length], ["Lease đang hiệu lực", leases.filter(x => x.status === "active").length],
      ["Adapter Vault", providers.filter(x => x.provider === "vault_http").length], ["Adapter CLI đám mây", providers.filter(x => String(x.provider).endsWith("_cli")).length]]}/>
    <div className="ui-grid is-2">
      <Panel title="Kết nối nhà cung cấp" desc="Không hiện giá trị bí mật nào">
        <Table rows={providers} empty="Chưa cấu hình nhà cung cấp nào." cols={[
          {label: "Tên", render: x => <><b>{x.name}</b><br/><small>{x.endpoint || "môi trường thực thi tại chỗ"}</small></>},
          {label: "Loại", render: x => <code>{x.provider}</code>},
          {label: "Trạng thái", render: x => <Pill s={x.enabled ? "enabled" : "disabled"}/>},
        ]}/>
      </Panel>
      <Panel title="Lease truy cập bí mật" desc="Gắn với runner/agent, có hạn">
        <Table rows={leases.slice(0, 14)} empty="Chưa có lease nào." cols={[
          {label: "Lease", render: x => <>#{x.id}</>},
          {label: "Tham chiếu / runner", render: x => <small>ref #{x.secret_reference_id} · runner {x.runner_lease_id || "—"}</small>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
