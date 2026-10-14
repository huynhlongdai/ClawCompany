"use client";
import {useEffect, useState} from "react";
import {apiV12} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Sandbox (v12): chạy build/test theo argv trong môi trường có chính sách. */
export function SandboxesConsole() {
  const q = useLoad(async () => {
    const [p, r, w] = await Promise.all([apiV12.sandboxProfiles(), apiV12.sandboxRuns(), apiV12.workspaces()]);
    return {profiles: p as Any[], runs: r as Any[], workspaces: w as Any[]};
  }, {profiles: [], runs: [], workspaces: []});
  const {data, reload} = q;
  const [ws, setWs] = useState(""), [profile, setProfile] = useState(""), [cmd, setCmd] = useState("python -V");
  const act = useAction();
  useEffect(() => {
    if (!ws && data.workspaces[0]) setWs(String(data.workspaces[0].id));
    if (!profile && data.profiles[0]) setProfile(String((data.profiles[0].profile || data.profiles[0]).id));
  }, [data, ws, profile]);
  const run = () => act.run("run", async () => {
    await apiV12.runSandbox({workspace_id: Number(ws), profile_id: Number(profile), purpose: "test", command: cmd.trim().split(/\s+/), secret_grant_ids: []}); await reload();
  }, "Đã chạy trong sandbox");
  return <LabBody q={q}>
    <Intro>Lệnh chạy theo argv, không nội suy shell. Adapter Docker đóng khi lỗi nếu không áp được chính sách mạng ra ngoài. Đầu ra có giới hạn; bí mật gắn dạng tệp tạm.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Chạy sandbox" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Chạy trong sandbox">
        <div className="ui-form">
          <Field label="Workspace"><select className="ui-select" value={ws} onChange={e => setWs(e.target.value)}>
            {!data.workspaces.length && <option value="">Chưa có workspace</option>}
            {data.workspaces.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          <Field label="Hồ sơ bảo mật"><select className="ui-select" value={profile} onChange={e => setProfile(e.target.value)}>
            {data.profiles.map((x: Any) => { const p = x.profile || x; return <option key={p.id} value={p.id}>{p.name} · {p.provider}</option>; })}</select></Field>
          <Field label="Lệnh"><input className="ui-input" value={cmd} onChange={e => setCmd(e.target.value)} style={{fontFamily: "var(--font-mono)"}}/></Field>
          <div><Button variant="primary" busy={act.busy === "run"} disabled={!ws || !profile} onClick={run}>Chạy</Button></div>
        </div>
      </Panel>
      <Panel title="Hồ sơ bảo mật" desc="Mạng, hệ tệp gốc, bộ nhớ, CPU">
        <Table rows={data.profiles.slice(0, 4).map((x: Any) => ({...(x.profile || x), _secure: x.policy?.secure_default}))} empty="Chưa có hồ sơ nào." cols={[
          {label: "Hồ sơ", render: p => <><b>{p.name}</b><br/><small>{p.provider} · {p.image}</small></>},
          {label: "Giới hạn", render: p => <small>mạng {p.network_mode} · root {p.read_only_root ? "chỉ đọc" : "ghi được"} · {p.memory_mb} MB · CPU {p.cpu_limit}</small>, hideSm: true},
          {label: "Chính sách", render: p => <Pill s={p._secure ? "ok" : "pending"} label={p._secure ? "An toàn mặc định" : "Cần xem lại"}/>},
        ]}/>
      </Panel>
    </div>
    <Panel title="Lịch sử chạy sandbox">
      <Table rows={data.runs} empty="Chưa có lượt chạy nào." cols={[
        {label: "Lượt", render: x => <>#{x.id}</>}, {label: "Mục đích", render: x => x.purpose},
        {label: "Workspace", render: x => <>#{x.workspace_id}</>, hideSm: true}, {label: "Mã nhà cung cấp", render: x => <code>{x.provider_run_id || "—"}</code>, hideSm: true},
        {label: "Mã thoát", render: x => x.exit_code ?? "—", num: true}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
