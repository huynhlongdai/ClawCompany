"use client";
import {useEffect, useState} from "react";
import {apiV12} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, LabBody, Intro, Panel, Pill, Table, short, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Chuyến phát hành / Triển khai (v12): bản phát hành gắn commit → môi trường, có dòng rollback. */
export function ReleasesConsole() {
  const q = useLoad(async () => {
    const [r, e, d] = await Promise.all([apiV12.releases(), apiV12.environments(), apiV12.deployments()]);
    return {releases: r as Any[], envs: e as Any[], deployments: d as Any[]};
  }, {releases: [], envs: [], deployments: []});
  const {data, reload} = q;
  const [repo, setRepo] = useState("1"), [version, setVersion] = useState("1.0.0"), [sha, setSha] = useState(""), [env, setEnv] = useState("");
  const act = useAction();
  useEffect(() => { if (!env && data.envs[0]) setEnv(String(data.envs[0].id)); }, [data.envs, env]);
  const create = () => act.run("create", async () => {
    await apiV12.createRelease({repository_id: Number(repo), version, commit_sha: sha, release_notes: "Tạo từ trang Chuyến phát hành", manifest: {source: "ui"}}); await reload();
  }, "Đã tạo bản phát hành");
  const deploy = (id: number) => act.run("d" + id, async () => { await apiV12.deployRelease(id, Number(env)); await reload(); }, "Đã gửi lệnh triển khai");
  return <LabBody q={q}>
    <Intro flow={["Commit", "Duyệt", "Môi trường"]}>Mỗi lượt triển khai ghim theo commit và nối với lượt trước để rollback. Production có thể cần duyệt trước khi triển khai.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Phát hành" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Tạo bản phát hành bất biến" desc="Bản phát hành phải trỏ tới một commit SHA Git">
        <div className="ui-form">
          <div className="ui-form-row">
            <Field label="Mã repository"><input className="ui-input" inputMode="numeric" value={repo} onChange={e => setRepo(e.target.value)}/></Field>
            <Field label="Phiên bản"><input className="ui-input" value={version} onChange={e => setVersion(e.target.value)}/></Field>
          </div>
          <Field label="Commit SHA" hint="SHA đầy đủ 40 ký tự"><input className="ui-input" value={sha} onChange={e => setSha(e.target.value)}/></Field>
          <div><Button variant="primary" busy={act.busy === "create"} disabled={!sha} onClick={create}>Tạo bản phát hành</Button></div>
        </div>
      </Panel>
      <Panel title="Môi trường đích" desc="Chọn nơi triển khai khi bấm Triển khai ở bảng dưới">
        {data.envs.length ? <div className="ui-list lab-rows">{data.envs.map(x => <label key={x.id} className="ui-row" style={{cursor: "pointer"}}>
          <input type="radio" name="env" checked={String(x.id) === env} onChange={() => setEnv(String(x.id))}/>
          <span className="ui-row-main"><span className="ui-row-title">{x.name}</span><span className="ui-row-meta">{x.environment_type} · {x.provider}</span></span>
          <span className="ui-row-end"><Pill s={x.require_approval ? "pending" : "ok"} label={x.require_approval ? "Cần duyệt" : "Trực tiếp"}/></span></label>)}</div>
          : <p className="ui-empty-line">Chưa có môi trường nào.</p>}
      </Panel>
    </div>
    <Panel title="Chuyến phát hành">
      <Table rows={data.releases} empty="Chưa có bản phát hành nào." cols={[
        {label: "Phiên bản", render: x => <><b>{x.version}</b><br/><small>{x.release_notes || "Không có ghi chú"}</small></>},
        {label: "Commit", render: x => <code>{short(x.commit_sha)}</code>, hideSm: true},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        {label: "", render: x => <Button size="sm" icon="arrow-right" disabled={!env} busy={act.busy === "d" + x.id} onClick={() => deploy(x.id)}>Triển khai</Button>},
      ]}/>
    </Panel>
    <Panel title="Lượt triển khai gần đây" desc="Dòng phát hành">
      <Table rows={data.deployments} empty="Chưa có lượt triển khai nào." cols={[
        {label: "Lượt", render: x => <>#{x.id}</>}, {label: "Bản phát hành", render: x => <>#{x.release_id}</>},
        {label: "Môi trường / trước đó", render: x => <small>môi trường #{x.environment_id} · trước #{x.previous_deployment_id || "—"}</small>, hideSm: true},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
