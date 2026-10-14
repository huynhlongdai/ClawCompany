"use client";
import {useState} from "react";
import {apiV12} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, KV, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Workspace phát triển (v12): thư mục làm việc cô lập theo tổ chức + việc, có hạn dùng. */
export function WorkspacesConsole() {
  const q = useLoad(async () => (await apiV12.workspaces()) as Any[], []);
  const [name, setName] = useState("Workspace tính năng"), [key, setKey] = useState(() => `feature-${Date.now().toString().slice(-5)}`), [repo, setRepo] = useState("");
  const act = useAction();
  const create = () => act.run("create", async () => {
    await apiV12.createWorkspace({organization_id: activeOrganizationId(), name, workspace_key: key, repository_id: repo ? Number(repo) : null, ttl_minutes: 720}); await q.reload();
  }, "Đã tạo workspace");
  const destroy = (id: number) => act.run("x" + id, async () => { await apiV12.destroyWorkspace(id); await q.reload(); }, "Đã huỷ workspace");
  return <LabBody q={q}>
    <Intro>Agent nhận một đường dẫn gói trong một tổ chức và một việc. Workspace có repository dùng Git worktree tách rời; workspace thường nằm dưới thư mục gốc phát triển đã cấu hình.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Workspace" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Tạo workspace cô lập" desc="Worktree của repository hoặc thư mục sạch có quản lý">
        <div className="ui-form">
          <Field label="Tên"><input className="ui-input" value={name} onChange={e => setName(e.target.value)}/></Field>
          <Field label="Khoá workspace"><input className="ui-input" value={key} onChange={e => setKey(e.target.value)}/></Field>
          <Field label="Mã repository (không bắt buộc)"><input className="ui-input" inputMode="numeric" value={repo} onChange={e => setRepo(e.target.value)} placeholder="1"/></Field>
          <div><Button variant="primary" busy={act.busy === "create"} onClick={create}>Tạo workspace</Button></div>
        </div>
      </Panel>
      <Panel title="Cam kết của workspace">
        <KV items={[["Dọn theo hạn dùng", "Bật (chỉ khi LAB_JOBS_ENABLED=true)"], ["Đi ngược thư mục", "Bị chặn"], ["Thư mục home dùng chung giữa agent", "Tắt"]]}/>
      </Panel>
    </div>
    <Panel title="Workspace phát triển" desc="Bề mặt cộng tác tạm thời, chia sẻ qua ClawCompany chứ không qua bộ nhớ cục bộ của từng model">
      <Table rows={q.data} empty="Chưa có workspace nào." cols={[
        {label: "Workspace", render: x => <><b>{x.name}</b><br/><code>{x.workspace_key}</code></>},
        {label: "Đường dẫn", render: x => <code>{x.root_path || "đang chuẩn bị…"}</code>, hideSm: true},
        {label: "Repo / chủ / base", render: x => <small>#{x.repository_id || "—"} · #{x.owner_member_id || "—"} · {x.base_ref || "—"}</small>, hideSm: true},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        {label: "", render: x => <Button size="sm" variant="danger" busy={act.busy === "x" + x.id} onClick={() => destroy(x.id)}>Huỷ</Button>},
      ]}/>
    </Panel>
  </LabBody>;
}
