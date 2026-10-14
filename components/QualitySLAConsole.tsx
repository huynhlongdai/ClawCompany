"use client";
import {apiV10} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useAction, useLoad} from "./lab/kit";

/* Chất lượng & hạn (v10): cổng QA cho artifact + hồ sơ SLA và sự cố trễ hạn. */
export function QualitySLAConsole() {
  const q = useLoad(async () => {
    const [a, b, c] = await Promise.all([apiV10.evaluations(), apiV10.slaIncidents(), apiV10.slaProfiles()]);
    return {evals: a as Any[], slas: b as Any[], profiles: c as Any[]};
  }, {evals: [], slas: [], profiles: []});
  const act = useAction();
  const {evals, slas, profiles} = q.data;
  return <LabBody q={q}>
    <Intro>Artifact được duyệt hoặc trả lại trước khi chạy tiếp; trễ hạn thành sự kiện và có thể báo quản lý hoặc Nina.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Kiểm SLA" onClose={() => act.setError(null)}/> : null}
    <Panel title="Tổng quan" actions={<Button variant="primary" busy={act.busy === "sla"} onClick={() => act.run("sla", async () => { await apiV10.runSlaCheck(); await q.reload(); }, "Đã kiểm SLA")}>Chạy kiểm SLA</Button>}>
      <Stats items={[["Lượt chấm QA", evals.length], ["Cần sửa", evals.filter(x => x.verdict === "changes_requested").length], ["SLA đang mở", slas.filter(x => x.status !== "resolved").length]]}/>
    </Panel>
    <div className="ui-grid is-2">
      <Panel title="Cổng QA">
        <Table rows={evals} empty="Chưa chấm artifact nào." cols={[
          {label: "Artifact", render: x => <>#{x.artifact_id}</>}, {label: "Điểm", render: x => Math.round(x.score), num: true}, {label: "Kết luận", render: x => <Pill s={x.verdict}/>},
        ]}/>
      </Panel>
      <Panel title="SLA & leo thang">
        <Table rows={[...profiles.map(x => ({id: "p" + x.id, t: x.name, s: `${x.resource_type} · ${x.completion_minutes} phút`, st: "info", l: "Hồ sơ"}) as Any),
          ...slas.map(x => ({id: "i" + x.id, t: `${x.resource_type} #${x.resource_id}`, s: x.summary, st: x.status}) as Any)]}
          empty="Chưa có hồ sơ SLA hay sự cố trễ hạn." cols={[{label: "Mục", render: x => <><b>{x.t}</b><br/><small>{x.s}</small></>}, {label: "", render: x => <Pill s={x.st} label={x.l}/>}]}/>
      </Panel>
    </div>
  </LabBody>;
}
