"use client";
import {useState} from "react";
import {activeOrganizationId} from "../lib/auth";
import {apiV10} from "../lib/api";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

/* Tin nhắn agent (v10): kênh tin nội bộ bền vững agent↔agent, Nina↔quản lý, người↔agent. */
export function AgentMessageBusConsole() {
  const q = useLoad(async () => (await apiV10.messages()) as Any[], []);
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [text, setText] = useState("Xem artifact mới nhất và gửi lại nhận xét.");
  const act = useAction();
  const send = () => act.run("send", async () => {
    await apiV10.sendMessage({organization_id: activeOrganizationId(), sender_member_id: from ? Number(from) : null, recipient_member_id: to ? Number(to) : null,
      thread_key: "ops-demo", subject: "Giao việc giữa agent", content: text, priority: "high"}); await q.reload();
  }, "Đã gửi tin");
  return <LabBody q={q}>
    <Intro>Tin nhắn nội bộ lưu lâu dài, không phụ thuộc vào một phiên chat LLM nào.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Gửi tin" onClose={() => act.setError(null)}/> : null}
    <div className="ui-grid is-side-l">
      <Panel title="Gửi tin nội bộ">
        <div className="ui-form">
          <div className="ui-form-row">
            <Field label="Từ (mã thành viên)"><input className="ui-input" inputMode="numeric" value={from} onChange={e => setFrom(e.target.value)} placeholder="không bắt buộc"/></Field>
            <Field label="Tới (mã thành viên)"><input className="ui-input" inputMode="numeric" value={to} onChange={e => setTo(e.target.value)}/></Field>
          </div>
          <Field label="Nội dung"><textarea className="ui-textarea" rows={3} value={text} onChange={e => setText(e.target.value)}/></Field>
          <div><Button variant="primary" busy={act.busy === "send"} onClick={send}>Gửi</Button></div>
        </div>
      </Panel>
      <Panel title="Tin gần đây">
        <Table rows={q.data.slice(0, 30)} empty="Chưa có tin nào." cols={[
          {label: "Tin", render: x => <><b>{x.subject || x.message_type}</b><br/><small>#{x.sender_member_id || "hệ thống"} → #{x.recipient_member_id || "mọi người"} · {x.thread_key}</small><br/>{x.content}</>},
          {label: "Ưu tiên", render: x => <Pill s={x.priority}/>},
        ]}/>
      </Panel>
    </div>
  </LabBody>;
}
