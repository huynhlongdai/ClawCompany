"use client";
import {apiV10} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Any, Intro, LabBody, Panel, Table, parseJson, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Mô phỏng (v10): thử "nếu… thì" về nhân sự, chi phí, tự chủ trước khi đổi công ty thật. */
export function DigitalTwinConsole() {
  const q = useLoad(async () => {
    const [a, b] = await Promise.all([apiV10.simulations(), apiV10.simulationRuns()]);
    return {scenarios: a as Any[], runs: b as Any[]};
  }, {scenarios: [], runs: []});
  const act = useAction();
  const run = (id: number) => act.run("r" + id, async () => { await apiV10.runSimulation(id); await q.reload(); }, "Đã chạy mô phỏng");
  return <LabBody q={q}>
    <Intro>Mô hình "nếu… thì" trước khi đổi nhân sự, chi phí hay mức tự chủ: sức chứa, chi phí dự kiến, việc tồn và điểm rủi ro.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Chạy mô phỏng" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-2">
      <Panel title="Kịch bản mô phỏng">
        <Table rows={q.data.scenarios} empty="Chưa có kịch bản nào. seed.py tạo sẵn một kịch bản mẫu." cols={[
          {label: "Kịch bản", render: s => <><b>{s.name}</b><br/><small>{s.description || s.status}</small></>},
          {label: "", render: s => <Button size="sm" busy={act.busy === "r" + s.id} onClick={() => run(s.id)}>Chạy</Button>},
        ]}/>
      </Panel>
      <Panel title="Kết quả mô phỏng">
        <Table rows={q.data.runs} empty="Chưa chạy mô phỏng nào." cols={[
          {label: "Kịch bản", render: r => <>#{r.scenario_id}</>}, {label: "Điểm", render: r => Math.round(r.score), num: true},
          {label: "Sức chứa / chi phí / tồn", render: r => { const x = parseJson<Any>(r.result_json, {});
            return <small>{x.expected_capacity_tasks ?? "—"} việc · ${x.expected_cost ?? "—"} · tồn {x.backlog_after_horizon ?? "—"}</small>; }},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
