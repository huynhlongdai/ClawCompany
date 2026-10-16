"use client";
import {useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV8} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {ErrorBanner, Notice} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useAction, useLoad} from "./lab/kit";

const DEMO = {industry: "Thương mại số", departments: [{name: "Tăng trưởng", agents: [{name: "Maya", role: "Trưởng tăng trưởng", skills: ["research", "analytics"]},
  {name: "Leo", role: "Chạy quảng cáo", skills: ["ads", "copy"]}]}, {name: "Vận hành", agents: [{name: "Iris", role: "Quản lý vận hành", skills: ["planning", "reporting"]}]}]};

/* Dựng công ty từ mẫu — đời cũ (v8). Luồng chính nay ở Công ty › Tạo & nhập. */
export function CompanyFactoryConsole() {
  const org = activeOrganizationId();
  const q = useLoad(async () => {
    const [t, j] = await Promise.all([api.marketplace(org), apiV8.companyFactoryJobs()]);
    return {templates: t as Any[], jobs: j as Any[]};
  }, {templates: [], jobs: []});
  const [name, setName] = useState("Nova Growth Studio"), [templateId, setTemplateId] = useState("");
  const act = useAction();
  const install = () => act.run("install", async () => {
    await apiV8.companyFactoryInstall({organization_id: org, company_name: name, template_id: templateId ? Number(templateId) : null, manifest: templateId ? {} : DEMO}); await q.reload();
  }, "Đã gửi lệnh dựng công ty");
  const jobs = q.data.jobs;
  return <PageFrame>
    <LabBody q={q}>
      <Notice>Trang đời cũ. Dựng công ty có trưởng phòng là agent và sơ đồ báo cáo nằm ở Công ty › Tạo & nhập.</Notice>
      <Intro flow={["Manifest", "Công ty", "Phòng ban", "Nhân sự AI", "Runtime"]}>Dựng một tổ chức thật (phòng ban + nhân sự AI) từ mẫu trong Kho mẫu hoặc mẫu demo có sẵn.</Intro>
      {act.error ? <ErrorBanner error={act.error} context="Dựng công ty" onClose={() => act.setError(null)}/> : null}
      <div className="ui-grid is-2">
        <Panel title="Dựng công ty">
          <div className="ui-form">
            <Field label="Tên công ty"><input className="ui-input" value={name} onChange={e => setName(e.target.value)}/></Field>
            <Field label="Mẫu"><select className="ui-select" value={templateId} onChange={e => setTemplateId(e.target.value)}>
              <option value="">Mẫu demo Growth Studio có sẵn</option>
              {q.data.templates.filter(t => t.template_type === "company").map(t => <option key={t.id} value={t.id}>{t.name} · v{t.version}</option>)}</select></Field>
            {!templateId && <pre className="lab-pre">{JSON.stringify(DEMO, null, 2)}</pre>}
            <div><Button variant="primary" busy={act.busy === "install"} disabled={!name} onClick={install}>Dựng công ty</Button></div>
          </div>
        </Panel>
        <Panel title="Kết quả dựng gần đây">
          <Stats items={[["Hoàn tất", jobs.filter(j => j.status === "ready").length], ["Một phần", jobs.filter(j => j.status === "partial").length], ["Lỗi", jobs.filter(j => j.status === "failed").length]]}/>
        </Panel>
      </div>
      <Panel title="Lịch sử dựng" desc="Mỗi lần dựng được ghi lại và chạy tiếp được ở mức job" actions={<Button size="sm" onClick={q.reload}>Tải lại</Button>}>
        <Table rows={jobs} empty="Chưa dựng công ty nào." cols={[
          {label: "Công ty", render: j => <><b>{j.company_name}</b><br/><small>job #{j.id}</small></>},
          {label: "Trạng thái", render: j => <Pill s={j.status}/>},
          {label: "Mã công ty", render: j => j.company_id || "—"},
          {label: "Kết quả", render: j => <code>{String(j.error || j.result_json || "—").slice(0, 120)}</code>, hideSm: true},
        ]}/>
      </Panel>
    </LabBody>
  </PageFrame>;
}
