"use client";
import {useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {apiV9} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {viTime} from "../lib/labels";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Mức tự chủ (v9): công ty được tự hành động tới đâu mà không cần founder can thiệp. */
export function AutonomyConsole() {
  const q = useLoad(async () => {
    const [p, o] = await Promise.all([apiV9.autonomyPolicy(), apiV9.recurringOperations()]);
    return {policy: p as Any, ops: o as Any[]};
  }, {policy: null as Any | null, ops: [] as Any[]});
  const [policy, setPolicy] = useState<Any | null>(null);
  useEffect(() => { if (q.data.policy) setPolicy(q.data.policy); }, [q.data.policy]);
  const act = useAction();
  const save = () => policy && act.run("save", async () => { await apiV9.saveAutonomyPolicy({...policy, organization_id: activeOrganizationId(), company_id: null}); await q.reload(); }, "Đã lưu chính sách");
  const run = (id: number) => act.run("r" + id, async () => { await apiV9.runRecurringNow(id); await q.reload(); }, "Đã chạy ngay");
  const num = (k: string) => <input className="ui-input" type="number" value={policy?.[k] ?? ""} onChange={e => setPolicy({...policy, [k]: Number(e.target.value)})}/>;
  return <PageFrame action={<Button variant="primary" busy={act.busy === "save"} disabled={!policy} onClick={save}>Lưu chính sách</Button>}>
    <LabBody q={q}>
      <Intro>Rào chắn chung cho cả tổ chức; chính sách riêng của từng công ty có thể ghi đè.</Intro>
      {act.error ? <ErrorBanner error={act.error} context="Chính sách tự chủ" onClose={() => act.setError(null)}/> : null}
      {policy && <Panel title="Chính sách tự chủ của tổ chức">
        <div className="ui-form-row">
          <Field label="Chế độ" hint="Thủ công = duyệt trước mỗi chu kỳ vận hành"><select className="ui-select" value={policy.mode} onChange={e => setPolicy({...policy, mode: e.target.value})}>
            <option value="manual">Thủ công</option><option value="supervised">Có giám sát</option><option value="autonomous">Tự chủ</option></select></Field>
          <Field label="Rủi ro tối đa được tự làm" hint="Cao hơn mức này thì tạo cổng duyệt"><select className="ui-select" value={policy.max_auto_risk} onChange={e => setPolicy({...policy, max_auto_risk: e.target.value})}>
            <option value="low">Thấp</option><option value="medium">Trung bình</option><option value="high">Cao</option></select></Field>
          <Field label="Lượt chạy đồng thời" hint="Giới hạn tải runtime">{num("max_concurrent_runs")}</Field>
          <Field label="Số lần thử lại" hint="Khôi phục tự động">{num("retry_limit")}</Field>
          <Field label="Ngân sách mỗi ngày (USD)" hint="Rào chắn cấp tổ chức">{num("daily_budget_limit")}</Field>
          <Field label="Hạn mức mỗi thao tác (USD)" hint="Chặn thao tác AI đắt">{num("per_action_limit")}</Field>
        </div>
      </Panel>}
      <Panel title="Việc vận hành định kỳ" desc="Celery Beat quét lịch và tạo chu kỳ vận hành cho Nina (đời cũ — việc định kỳ mới nằm ở mục Việc định kỳ)">
        <Table rows={q.data.ops} empty="Chưa có việc định kỳ nào." cols={[
          {label: "Việc", render: o => <><b>{o.name}</b><br/><small>{o.operation_type}</small></>},
          {label: "Lịch", render: o => <><code>{o.schedule}</code><br/><small>{o.timezone}</small></>, hideSm: true},
          {label: "Lần gần nhất", render: o => <Pill s={o.last_status}/>}, {label: "Lần tới", render: o => viTime(o.next_run_at), nowrap: true, hideSm: true},
          {label: "", render: o => <Button size="sm" busy={act.busy === "r" + o.id} onClick={() => run(o.id)}>Chạy ngay</Button>},
        ]}/>
      </Panel>
    </LabBody>
  </PageFrame>;
}
