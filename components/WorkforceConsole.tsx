"use client";
import {useMemo, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV8} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button, ButtonLink} from "./ui/Button";
import {Dialog} from "./ui/Dialog";
import {ErrorBanner, Notice} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, LabBody, Panel, Pill, Stats, Table, useAction, useLoad} from "./lab/kit";

/* Tuyển agent đời cũ (v8): sổ nhân sự AI + lịch sử cấp phát. Luồng chính nay ở Đội ngũ › Agent. */
export function WorkforceConsole() {
  const org = activeOrganizationId();
  const q = useLoad(async () => {
    const [a, m, c, d, j] = await Promise.all([api.agents(), api.members(), api.companies(org), api.departments(), apiV8.provisioningJobs()]);
    return {rows: a as Any[], members: m as Any[], companies: c as Any[], departments: d as Any[], jobs: j as Any[]};
  }, {rows: [], members: [], companies: [], departments: [], jobs: []});
  const {data} = q;
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({name: "Ava", role: "Phân tích tăng trưởng", company_id: "", department_id: "", model: "", runtime_agent_id: ""});
  const act = useAction();
  const memberMap = useMemo(() => Object.fromEntries(data.members.map(x => [x.id, x])), [data.members]);
  const deps = form.company_id ? data.departments.filter(d => String(d.company_id) === form.company_id) : data.departments;
  const hire = () => act.run("hire", async () => {
    await apiV8.hireAgent({organization_id: org, name: form.name, role: form.role, company_id: form.company_id ? Number(form.company_id) : null,
      department_id: form.department_id ? Number(form.department_id) : null, model: form.model, runtime_agent_id: form.runtime_agent_id,
      manifest: {skills: ["company.context", "company.tasks.list"], policy: {mode: "scoped"}}});
    setShow(false); await q.reload();
  }, "Đã tuyển và gửi cấp phát");
  return <PageFrame action={<Button variant="primary" icon="plus" onClick={() => setShow(true)}>Tuyển nhân sự AI</Button>}>
    <LabBody q={q}>
      <Notice>Trang đời cũ. Tuyển agent đầy đủ (5 file hồ sơ, quản lý, ngân sách) ở <ButtonLink href="/app/team?tab=ai" size="sm" variant="ghost">Đội ngũ › Agent</ButtonLink></Notice>
      <Stats items={[["Nhân sự AI", data.rows.length], ["Đang hoạt động", data.rows.filter(x => x.lifecycle === "active").length],
        ["Lượt cấp phát", data.jobs.length, `${data.jobs.filter(x => x.status === "failed").length} lỗi`], ["Chi phí 30 ngày", `$${data.rows.reduce((a, b) => a + (b.cost_30d || 0), 0).toFixed(1)}`]]}/>
      {act.error ? <ErrorBanner error={act.error} context="Tuyển agent" onClose={() => act.setError(null)}/> : null}
      <Panel title="Sổ nhân sự AI" desc="Thành viên ↔ agent ↔ runtime OpenClaw" actions={<Button size="sm" onClick={q.reload}>Tải lại</Button>}>
        <Table rows={data.rows} empty="Chưa có nhân sự AI nào." cols={[
          {label: "Nhân sự", render: a => <><b>{memberMap[a.member_id]?.name || `Agent #${a.id}`}</b><br/><small>{memberMap[a.member_id]?.role || "—"}</small></>},
          {label: "Mã runtime", render: a => <code>{a.runtime_agent_id}</code>, hideSm: true},
          {label: "Model", render: a => a.model || "mặc định", hideSm: true},
          {label: "Trạng thái", render: a => <Pill s={a.lifecycle}/>},
          {label: "Rủi ro", render: a => <Pill s={a.risk}/>},
        ]}/>
      </Panel>
      <Panel title="Lịch sử cấp phát" desc="Tạo ở ClawCompany → tạo trên runtime → sẵn sàng / lỗi">
        <Table rows={data.jobs.slice(0, 8)} empty="Chưa có lượt cấp phát nào." cols={[
          {label: "Nhân sự", render: j => <><b>{j.name}</b><br/><small>{j.role}</small></>},
          {label: "Mã runtime", render: j => <code>{j.runtime_agent_id}</code>, hideSm: true},
          {label: "Trạng thái", render: j => <>{<Pill s={j.status}/>}{j.error ? <><br/><small>{j.error}</small></> : null}</>},
        ]}/>
      </Panel>
    </LabBody>
    {show && <Dialog title="Tuyển nhân sự AI" onClose={() => setShow(false)} actions={<>
      <Button onClick={() => setShow(false)}>Huỷ</Button>
      <Button variant="primary" busy={act.busy === "hire"} disabled={!form.name || !form.role} onClick={hire}>Tuyển và cấp phát</Button></>}>
      <div className="ui-form">
        <Field label="Tên"><input className="ui-input" value={form.name} onChange={e => setForm({...form, name: e.target.value})}/></Field>
        <Field label="Vai trò"><input className="ui-input" value={form.role} onChange={e => setForm({...form, role: e.target.value})}/></Field>
        <Field label="Công ty"><select className="ui-select" value={form.company_id} onChange={e => setForm({...form, company_id: e.target.value, department_id: ""})}>
          <option value="">Cấp tổ chức</option>{data.companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="Phòng ban"><select className="ui-select" value={form.department_id} onChange={e => setForm({...form, department_id: e.target.value})}>
          <option value="">Không</option>{deps.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
        <Field label="Model"><input className="ui-input" placeholder="Mặc định của runtime" value={form.model} onChange={e => setForm({...form, model: e.target.value})}/></Field>
        <Field label="Mã agent runtime"><input className="ui-input" placeholder="Tự sinh" value={form.runtime_agent_id} onChange={e => setForm({...form, runtime_agent_id: e.target.value})}/></Field>
      </div>
    </Dialog>}
  </PageFrame>;
}
