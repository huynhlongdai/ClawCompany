"use client";
import {useEffect, useState} from "react";
import {apiV11} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, KV, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

const STAGES = ["queued", "preparing", "prepared", "tests_passed", "reviewing", "merged"];
const STAGE_VI: Record<string, string> = {queued: "Trong hàng", preparing: "Đang chuẩn bị", prepared: "Đã chuẩn bị", tests_passed: "Test đạt", reviewing: "Đang review", merged: "Đã merge"};

/* Phòng thí nghiệm · Pipeline giao hàng (v11): kết quả agent → commit đã test → merge đã review. */
export function RepositoryDeliveryConsole() {
  const q = useLoad(async () => {
    const [r, d] = await Promise.all([apiV11.repositories(), apiV11.deliveries()]);
    return {repos: r as Any[], runs: d as Any[]};
  }, {repos: [], runs: []});
  const {data, reload} = q;
  const [selected, setSelected] = useState<Any | null>(null);
  const [repo, setRepo] = useState(""), [bundle, setBundle] = useState("feature-demo"), [pipeline, setPipeline] = useState("");
  const act = useAction();
  useEffect(() => { if (!repo && data.repos[0]) setRepo(String(data.repos[0].id)); }, [data.repos, repo]);
  const open = (id: number) => act.run("open", async () => setSelected(await apiV11.delivery(id) as Any));
  const create = () => act.run("create", async () => {
    const x = await apiV11.createDelivery({repository_id: Number(repo), pipeline_id: pipeline ? Number(pipeline) : null, artifact_bundle_key: bundle, initiated_by_member_id: null}) as Any;
    await reload(); setSelected(await apiV11.delivery(x.id) as Any);
  }, "Đã tạo lượt giao hàng");
  const step = (kind: string, id: number) => act.run(kind + id, async () => {
    if (kind === "prepare") await apiV11.prepareDelivery(id);
    if (kind === "tests") await apiV11.testDelivery(id);
    if (kind === "mr") await apiV11.openMergeRequest(id);
    if (kind === "merge") await apiV11.mergeDelivery(id);
    await reload(); setSelected(await apiV11.delivery(id) as Any);
  });
  const sel = selected;
  return <LabBody q={q}>
    <Intro flow={["Chuẩn bị", "Test", "Review", "Merge"]}>
      Agent commit nhận phiên bản artifact bất biến, ghi vào một Git worktree riêng, sinh artifact bản vá, chạy bộ test đã cấu hình và chỉ merge khi các cổng chính sách đều đạt.
    </Intro>
    {act.error ? <ErrorBanner error={act.error} context="Thao tác giao hàng" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Bắt đầu giao hàng" desc="Dùng khoá gói artifact do bất kỳ agent nào tạo">
        <div className="ui-form">
          <Field label="Repository"><select className="ui-select" value={repo} onChange={e => setRepo(e.target.value)}>
            {!data.repos.length && <option value="">Chưa có repository</option>}
            {data.repos.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          <Field label="Gói artifact"><input className="ui-input" value={bundle} onChange={e => setBundle(e.target.value)}/></Field>
          <Field label="Mã pipeline (không bắt buộc)"><input className="ui-input" inputMode="numeric" value={pipeline} onChange={e => setPipeline(e.target.value)}/></Field>
          <div><Button variant="primary" busy={act.busy === "create"} disabled={!repo} onClick={create}>Tạo lượt giao hàng</Button></div>
        </div>
      </Panel>
      <Panel title="Lượt đang xem" desc="Cổng merge tính từ trạng thái test và review thật">
        {sel ? <>
          <KV items={[["Lượt", `#${sel.delivery.id}`], ["Nhánh", sel.delivery.source_branch || "chưa có"], ["Test", <Pill key="t" s={sel.gate.latest_test_status || "pending"}/>],
            ["Duyệt", `${sel.gate.approvals}/${sel.gate.required_approvals}`], ["Cổng merge", <Pill key="g" s={sel.gate.allowed ? "ok" : "pending"} label={sel.gate.allowed ? "Đã mở" : "Chờ các kiểm tra bắt buộc"}/>],
            ["Commit", <code key="c">{sel.delivery.head_commit_sha || "chưa tạo commit"}</code>]]}/>
        </> : <p className="ui-empty-line">Chọn một lượt giao hàng ở bảng dưới.</p>}
      </Panel>
    </div>
    <Panel title="Các lượt giao hàng" desc="Mỗi lượt một nhánh riêng; truy được artifact → commit">
      <Table rows={data.runs} empty="Chưa có lượt giao hàng nào." cols={[
        {label: "Lượt", render: x => <button type="button" className="ui-link" onClick={() => open(x.id)}>#{x.id} · {x.artifact_bundle_key}</button>},
        {label: "Nhánh", render: x => <small>{x.source_branch || "chưa có nhánh"} → {x.target_branch}</small>, hideSm: true},
        {label: "Tiến độ", render: x => <span className="ui-meter" title={STAGE_VI[x.status] || x.status} style={{display: "block", width: 80}}><i style={{width: `${((STAGES.indexOf(x.status) + 1) / STAGES.length) * 100}%`}}/></span>, hideSm: true},
        {label: "Trạng thái", render: x => <Pill s={x.status} label={STAGE_VI[x.status]}/>},
        {label: "", render: x => <div className="ui-toolbar" style={{flexWrap: "nowrap"}}>
          <Button size="sm" busy={act.busy === "prepare" + x.id} onClick={() => step("prepare", x.id)}>Chuẩn bị</Button>
          <Button size="sm" busy={act.busy === "tests" + x.id} onClick={() => step("tests", x.id)}>Chạy test</Button>
          <Button size="sm" busy={act.busy === "mr" + x.id} onClick={() => step("mr", x.id)}>Mở MR</Button>
          <Button size="sm" variant="primary" busy={act.busy === "merge" + x.id} onClick={() => step("merge", x.id)}>Merge</Button></div>},
      ]}/>
    </Panel>
  </LabBody>;
}
