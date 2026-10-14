"use client";
import {useEffect, useState} from "react";
import {activeOrganizationId} from "../lib/auth";
import {apiV11} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, KV, LabBody, Panel, Pill, Table, short, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Repository (v11): sổ đăng ký kho mã theo tổ chức + trạng thái Git chính xác. */
export function RepositoryRegistryConsole() {
  const q = useLoad(async () => (await apiV11.repositories()) as Any[], []);
  const [selected, setSelected] = useState<Any | null>(null);
  const [name, setName] = useState("nova-product"), [project, setProject] = useState("");
  const act = useAction();
  const inspect = (id: number) => act.run("i" + id, async () => setSelected(await apiV11.repository(id) as Any));
  useEffect(() => { if (!selected && q.data[0]) inspect(q.data[0].id); /* eslint-disable-next-line */ }, [q.data]);
  const create = () => act.run("create", async () => {
    await apiV11.createRepository({organization_id: activeOrganizationId(), name, provider: "local", default_branch: "main", project_id: project ? Number(project) : null, initialize: true}); await q.reload();
  }, "Đã tạo repository");
  const st = selected?.state || {};
  return <LabBody q={q}>
    <Intro flow={["Gói artifact", "Sổ repository", "Worktree riêng", "Agent commit"]}>Git cục bộ dùng được ngay; GitHub và remote khác nằm sau chứng chỉ của nhà cung cấp.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Repository" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Đăng ký repository">
        <div className="ui-form">
          <Field label="Tên"><input className="ui-input" value={name} onChange={e => setName(e.target.value)}/></Field>
          <Field label="Mã dự án (không bắt buộc)"><input className="ui-input" inputMode="numeric" value={project} onChange={e => setProject(e.target.value)}/></Field>
          <div><Button variant="primary" busy={act.busy === "create"} onClick={create}>Tạo và khởi tạo</Button></div>
        </div>
      </Panel>
      <Panel title="Trạng thái repository" desc="Nhánh, HEAD và sạch/có thay đổi — đọc thẳng từ Git">
        {selected ? <KV items={[["Tên", <b key="n">{selected.repository?.name}</b>], ["Nhà cung cấp", selected.repository?.provider], ["Đường dẫn", <code key="p">{st.path || "chưa khởi tạo"}</code>],
          ["Nhánh", st.branch || "—"], ["HEAD", <code key="h">{short(st.head)}</code>], ["Tình trạng", <Pill key="s" s={st.status || "clean"}/>]]}/>
          : <p className="ui-empty-line">Chọn một repository ở bảng dưới.</p>}
      </Panel>
    </div>
    <Panel title="Sổ repository" desc="Kho mã theo tổ chức và đích giao hàng">
      <Table rows={q.data} empty="Chưa đăng ký repository nào." cols={[
        {label: "Tên", render: x => <b>{x.name}</b>}, {label: "Nhà cung cấp", render: x => x.provider, hideSm: true},
        {label: "Nhánh", render: x => <code>{x.default_branch}</code>}, {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        {label: "", render: x => <Button size="sm" busy={act.busy === "i" + x.id} onClick={() => inspect(x.id)}>Xem</Button>},
      ]}/>
    </Panel>
  </LabBody>;
}
