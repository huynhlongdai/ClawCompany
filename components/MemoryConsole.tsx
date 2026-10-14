"use client";
import {useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {apiV9} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, KV, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

const TYPES: [string, string][] = [["principle", "Nguyên tắc"], ["fact", "Sự thật"], ["decision", "Quyết định"], ["outcome", "Kết quả"], ["lesson", "Bài học"]];

/* Bộ nhớ tổ chức (v9): ghi và tìm lại nguyên tắc, quyết định, kết quả cho Nina, quản lý và agent. */
export function MemoryConsole() {
  const org = activeOrganizationId();
  const [query, setQuery] = useState("");
  const q = useLoad(async () => (await apiV9.memorySearch(query)) as Any[], []);
  const [content, setContent] = useState("Nova ưu tiên niềm tin khách hàng và lợi nhuận bền vững hơn tăng trưởng ảo."), [type, setType] = useState("principle");
  const act = useAction();
  const add = () => act.run("add", async () => {
    await apiV9.createMemory({organization_id: org, memory_type: type, content, source_type: "founder", source_id: "manual", importance: 5, confidence: 1, tags: ["founder"]});
    setContent(""); await q.reload();
  }, "Đã ghi nhớ");
  const label = (k: string) => TYPES.find(x => x[0] === k)?.[1] || k;
  return <PageFrame>
    <LabBody q={q}>
      {act.error ? <ErrorBanner error={act.error} context="Ghi nhớ" onClose={() => act.setError(null)}/> : null}
      <div className="ui-grid is-2">
        <Panel title="Ghi nhớ" desc="Nguyên tắc, sự thật, quyết định, kết quả và bài học">
          <div className="ui-form">
            <Field label="Loại"><select className="ui-select" value={type} onChange={e => setType(e.target.value)}>{TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <Field label="Nội dung"><textarea className="ui-textarea" rows={3} value={content} onChange={e => setContent(e.target.value)}/></Field>
            <div><Button variant="primary" busy={act.busy === "add"} disabled={!content.trim()} onClick={add}>Ghi nhớ</Button></div>
          </div>
        </Panel>
        <Panel title="Cách bộ nhớ hoạt động">
          <KV items={[["Phạm vi", "tổ chức / công ty / dự án"], ["Trọng số", "mức quan trọng + độ tin cậy"], ["Nguồn gốc", "ghi rõ ai/đâu tạo ra"], ["Dùng lại", "Nina tìm trước khi lập kế hoạch"]]}/>
        </Panel>
      </div>
      <Panel title="Tìm trong bộ nhớ" desc={`${q.data.length} kết quả`}>
        <form className="ui-toolbar" style={{marginBottom: 12}} onSubmit={e => { e.preventDefault(); q.reload(); }}>
          <input className="ui-input" style={{flex: "1 1 220px", width: "auto"}} placeholder="Tìm nguyên tắc, kết quả, quyết định…" value={query} onChange={e => setQuery(e.target.value)}/>
          <Button type="submit" icon="search" busy={q.loading}>Tìm</Button>
        </form>
        <Table rows={q.data} empty="Không có ghi nhớ nào khớp." cols={[
          {label: "Loại", render: x => <Pill s="info" label={label(x.memory_type)}/>},
          {label: "Nội dung", render: x => <>{x.content}<br/><small>quan trọng {x.importance}/5 · tin cậy {Math.round((x.confidence || 0) * 100)}% · {x.source_type}</small></>},
        ]}/>
      </Panel>
    </LabBody>
  </PageFrame>;
}
