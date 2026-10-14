"use client";
import {useState} from "react";
import {apiV11} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, KV, LabBody, Panel, Pill, Rows, Table, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Review mã (v11): người + agent review đúng commit và bản vá của lượt giao hàng. */
export function CodeReviewConsole() {
  const q = useLoad(async () => (await apiV11.deliveries()) as Any[], []);
  const [detail, setDetail] = useState<Any | null>(null);
  const [reviewer, setReviewer] = useState("");
  const act = useAction();
  const inspect = (id: number) => act.run("open", async () => setDetail(await apiV11.delivery(id) as Any));
  const request = () => detail && reviewer && act.run("assign", async () => {
    await apiV11.requestReview(detail.delivery.id, {reviewer_member_id: Number(reviewer)}); setDetail(await apiV11.delivery(detail.delivery.id) as Any);
  }, "Đã giao người review");
  const decide = (id: number, verdict: string) => act.run("d" + id, async () => {
    await apiV11.decideReview(id, {verdict, score: verdict === "approve" ? 95 : 60, summary: verdict === "approve" ? "Sẵn sàng merge" : "Cần sửa trước khi merge", findings: []});
    if (detail) setDetail(await apiV11.delivery(detail.delivery.id) as Any);
  }, verdict === "approve" ? "Đã duyệt" : "Đã yêu cầu sửa");
  return <LabBody q={q}>
    <Intro>Agent review và người review cùng xem đúng commit và artifact bản vá của lượt giao hàng. Danh tính người review gắn với tổ chức; quyết định là bản ghi bất biến.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Review mã" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Hàng đợi review" desc="Chọn một lượt giao hàng">
        <Rows rows={q.data} empty="Chưa có lượt giao hàng nào cần review." onPick={x => inspect(x.id)} picked={x => detail?.delivery?.id === x.id}
          title={x => `#${x.id} · ${x.artifact_bundle_key}`} meta={x => x.source_branch || "chưa chuẩn bị"} end={x => <Pill s={x.status}/>}/>
      </Panel>
      <Panel title="Giao người review">
        <div className="ui-form-row" style={{alignItems: "end"}}>
          <Field label="Mã thành viên người review"><input className="ui-input" inputMode="numeric" value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="vd. 4"/></Field>
          <div><Button variant="primary" disabled={!detail || !reviewer} busy={act.busy === "assign"} onClick={request}>Giao</Button></div>
        </div>
        {detail ? <div style={{marginTop: 12}}><KV items={[["Artifact bản vá", `#${detail.delivery.patch_artifact_id || "—"}`], ["Commit", <code key="c">{detail.delivery.head_commit_sha || "Chuẩn bị lượt trước"}</code>]]}/></div>
          : <p className="ui-empty-line">Chọn một lượt ở bên cạnh trước.</p>}
      </Panel>
    </div>
    {detail && <Panel title={`Quyết định review · lượt #${detail.delivery.id}`}
      desc={`${detail.gate.approvals}/${detail.gate.required_approvals} lượt duyệt · test: ${detail.gate.latest_test_status || "chưa chạy"}`}>
      <Table rows={detail.reviews || []} empty="Chưa giao ai review." cols={[
        {label: "Người review", render: (x: Any) => <>#{x.reviewer_member_id || x.reviewer_agent_id}</>, nowrap: true},
        {label: "Nhận xét", render: (x: Any) => x.summary || "Đang chờ người review quyết định."},
        {label: "Kết luận", render: (x: Any) => <Pill s={x.verdict || x.status}/>},
        {label: "", render: (x: Any) => x.status === "pending" ? <div className="ui-toolbar" style={{flexWrap: "nowrap"}}>
          <Button size="sm" variant="primary" busy={act.busy === "d" + x.id} onClick={() => decide(x.id, "approve")}>Duyệt</Button>
          <Button size="sm" onClick={() => decide(x.id, "changes_requested")}>Yêu cầu sửa</Button></div> : null},
      ]}/>
    </Panel>}
  </LabBody>;
}
