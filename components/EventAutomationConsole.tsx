"use client";
import {useState} from "react";
import {activeOrganizationId} from "../lib/auth";
import {apiV10} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

/* Nhật ký sự kiện (v10): bus sự kiện bền vững + bộ trigger "khi … thì …". */
export function EventAutomationConsole() {
  const q = useLoad(async () => {
    const [a, b] = await Promise.all([apiV10.events(), apiV10.triggers()]);
    return {events: a as Any[], triggers: b as Any[]};
  }, {events: [], triggers: []});
  const [etype, setEtype] = useState("artifact.created");
  const act = useAction();
  const emit = () => act.run("emit", async () => {
    await apiV10.createEvent({organization_id: activeOrganizationId(), event_type: etype, source: "founder_cockpit", payload: {demo: true}}); await q.reload();
  }, "Đã phát sự kiện");
  const dispatch = (id: number) => act.run("d" + id, async () => { await apiV10.dispatchEvent(id); await q.reload(); }, "Đã xử lý sự kiện");
  return <LabBody q={q}>
    <Intro>Mọi thay đổi quan trọng có thể thành một sự kiện của công ty, và trigger biến sự kiện thành hành động (mẫu → điều kiện → hành động).</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Sự kiện" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-side">
      <Panel title="Sự kiện gần đây" desc="40 sự kiện mới nhất">
        <div className="ui-form-row" style={{alignItems: "end", marginBottom: 12}}>
          <Field label="Loại sự kiện"><input className="ui-input" value={etype} onChange={e => setEtype(e.target.value)} style={{fontFamily: "var(--font-mono)"}}/></Field>
          <div><Button variant="primary" busy={act.busy === "emit"} onClick={emit}>Phát sự kiện thử</Button></div>
        </div>
        <Table rows={q.data.events.slice(0, 40)} empty="Chưa có sự kiện nào." cols={[
          {label: "Sự kiện", render: e => <><code>{e.event_type}</code><br/><small>#{e.id}</small></>},
          {label: "Nguồn", render: e => e.source, hideSm: true},
          {label: "Trạng thái", render: e => <Pill s={e.status}/>},
          {label: "", render: e => <Button size="sm" busy={act.busy === "d" + e.id} onClick={() => dispatch(e.id)}>Xử lý</Button>},
        ]}/>
      </Panel>
      <Panel title="Trigger" desc="Khi … thì …">
        <Table rows={q.data.triggers} empty="Chưa cấu hình trigger nào (POST /api/v10/triggers hoặc seed.py)." cols={[
          {label: "Khi", render: t => <code>{t.event_pattern}</code>}, {label: "Thì", render: t => <><code>{t.action_type}</code><br/><small>{t.name}</small></>},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
