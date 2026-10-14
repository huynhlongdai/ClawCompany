"use client";
import {useState} from "react";
import {activeOrganizationId} from "../lib/auth";
import {apiV10} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Table, short, useAction, useLoad} from "./lab/kit";

/* Sản phẩm & bàn giao (v10): kho artifact có phiên bản + hàng bàn giao giữa agent. */
export function ArtifactHandoffConsole() {
  const q = useLoad(async () => {
    const [a, b] = await Promise.all([apiV10.artifacts(), apiV10.handoffs()]);
    return {items: a as Any[], handoffs: b as Any[]};
  }, {items: [], handoffs: []});
  const [name, setName] = useState("feature.ts"), [path, setPath] = useState("src/feature.ts"), [content, setContent] = useState("export function feature(){ return 'ready'; }"),
    [bundle, setBundle] = useState("feature-demo"), [target, setTarget] = useState("");
  const act = useAction();
  const create = () => act.run("create", async () => {
    await apiV10.createArtifact({organization_id: activeOrganizationId(), name, logical_path: path, bundle_key: bundle, artifact_type: "source_code", mime_type: "text/plain", content_text: content}); await q.reload();
  }, "Đã lưu phiên bản");
  const handoff = (id: number) => {
    const member = Number(target);
    if (!member) { act.setError(new Error("Nhập mã thành viên nhận ở ô “Người nhận bàn giao” trước khi bàn giao.")); return; }
    act.run("h" + id, async () => {
      await apiV10.handoffArtifact(id, {to_member_id: member, purpose: "continue_work", instructions: "Làm tiếp từ đúng phiên bản artifact này. Giữ đường dẫn logic và trả về phiên bản mới khi xong."}); await q.reload();
    }, "Đã bàn giao");
  };
  const qa = (id: number) => act.run("q" + id, async () => { await apiV10.evaluateArtifact(id, {rubric: {min_chars: 20, pass_score: 80}}); await q.reload(); }, "Đã chấm QA");
  return <LabBody q={q}>
    <Intro flow={["Agent A", "Kho artifact", "Hàng bàn giao", "Agent B / agent commit"]}>Agent nộp đúng nội dung mã hay sản phẩm kể cả khi không có quyền GitHub; mỗi lần nộp là một phiên bản bất biến có checksum.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Artifact" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Nộp artifact mã nguồn">
        <div className="ui-form">
          <div className="ui-form-row">
            <Field label="Gói"><input className="ui-input" value={bundle} onChange={e => setBundle(e.target.value)}/></Field>
            <Field label="Tên"><input className="ui-input" value={name} onChange={e => setName(e.target.value)}/></Field>
          </div>
          <Field label="Đường dẫn logic"><input className="ui-input" value={path} onChange={e => setPath(e.target.value)}/></Field>
          <Field label="Nội dung"><textarea className="ui-textarea" rows={4} value={content} onChange={e => setContent(e.target.value)} style={{fontFamily: "var(--font-mono)"}}/></Field>
          <div><Button variant="primary" busy={act.busy === "create"} onClick={create}>Lưu phiên bản</Button></div>
        </div>
      </Panel>
      <Panel title="Bàn giao" desc="Ví dụ: người review, agent QA, agent commit">
        <Field label="Người nhận bàn giao (mã thành viên)"><input className="ui-input" inputMode="numeric" value={target} onChange={e => setTarget(e.target.value)} placeholder="vd. 4"/></Field>
        <div style={{marginTop: 12}}><Table rows={q.data.handoffs.slice(0, 12)} empty="Chưa có lần bàn giao nào." cols={[
          {label: "Artifact", render: h => <>#{h.artifact_id}</>}, {label: "Tới", render: h => <small>#{h.to_member_id} · {h.purpose}</small>}, {label: "", render: h => <Pill s={h.status}/>},
        ]}/></div>
      </Panel>
    </div>
    <Panel title="Kho artifact" desc="Phiên bản bất biến + checksum + đường dẫn logic + ngữ cảnh người tạo">
      <Table rows={q.data.items} empty="Chưa có artifact nào." cols={[
        {label: "Artifact", render: x => <><b>{x.logical_path || x.name}</b><br/><small>{x.artifact_type} · v{x.version} · {x.bundle_key || "không gói"}</small></>},
        {label: "Checksum", render: x => <code>{short(x.content_sha256) || "—"}</code>, hideSm: true},
        {label: "", render: x => <div className="ui-toolbar" style={{flexWrap: "nowrap"}}>
          <Button size="sm" busy={act.busy === "h" + x.id} onClick={() => handoff(x.id)}>Bàn giao</Button>
          <Button size="sm" busy={act.busy === "q" + x.id} onClick={() => qa(x.id)}>Chấm QA</Button></div>},
      ]}/>
    </Panel>
  </LabBody>;
}
