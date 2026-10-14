"use client";
import {useEffect, useMemo, useState} from "react";
import {Button} from "./ui/Button";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {LogoLockup} from "./Logo";
import {describeError} from "../lib/api";
import {getLocale, t} from "../lib/i18n";

/* Cổng khách hàng · trò chuyện với nhân sự AI được gán (luồng sự kiện chạy qua phiên OpenClaw). */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";
type Chat = {id: number; conversation_id: number; agent_id: number; agent_name: string; title: string; runtime_session_key: string};
type Msg = {id: number; sender_name: string; content: string; message_type: string; created_at: string};
function portalToken() { return typeof window === "undefined" ? null : localStorage.getItem("clawcompany_portal_token"); }
async function pfetch(path: string, init: RequestInit = {}) {
  const tk = portalToken();
  const r = await fetch(`${API_BASE}${path}`, {...init, headers: {"Content-Type": "application/json", "Accept-Language": getLocale(), ...(tk ? {Authorization: `Bearer ${tk}`} : {}), ...(init.headers || {})}});
  if (!r.ok) throw describeError(r.status, await r.text());
  return r;
}

export function CustomerChat() {
  const [chats, setChats] = useState<Chat[]>([]), [selected, setSelected] = useState<number | undefined>(), [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState(""), [status, setStatus] = useState(""), [error, setError] = useState<unknown>(null), [errCtx, setErrCtx] = useState("");
  const queryAgent = useMemo(() => typeof window !== "undefined" ? Number(new URLSearchParams(location.search).get("agent")) : 0, []);
  const fail = (e: unknown, ctx: string) => { setError(e); setErrCtx(ctx); };
  async function loadChats() {
    try {
      let j = await (await pfetch("/portal/chats")).json();
      if (queryAgent) {
        const found = j.find((c: Chat) => c.agent_id === queryAgent);
        if (found) setSelected(found.id);
        else { const cj = await (await pfetch("/portal/chats", {method: "POST", body: JSON.stringify({agent_id: queryAgent, title: t("portal.new_chat")})})).json(); j = [cj, ...j]; setSelected(cj.id); }
      } else if (!selected && j.length) setSelected(j[0].id);
      setChats(j);
    } catch (e) { fail(e, t("portal.load_fail")); }
  }
  async function loadMessages(id: number) { try { setMessages(await (await pfetch(`/portal/chats/${id}/messages`)).json()); } catch (e) { fail(e, t("portal.load_fail")); } }
  useEffect(() => { if (!portalToken()) { location.href = "/portal"; return; } loadChats(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { if (selected) loadMessages(selected); }, [selected]);
  async function streamRun(chatId: number, runId: string) {
    setStatus(t("portal.working"));
    const r = await fetch(`${API_BASE}/portal/chats/${chatId}/runs/${runId}/events`, {headers: {Authorization: `Bearer ${portalToken()}`, "Accept-Language": getLocale()}});
    if (!r.ok) { setStatus(""); throw describeError(r.status, await r.text()); }
    const reader = r.body?.getReader(); const decoder = new TextDecoder(); let buf = "";
    while (reader) {
      const {done, value} = await reader.read(); if (done) break;
      buf += decoder.decode(value, {stream: true}); const blocks = buf.split("\n\n"); buf = blocks.pop() || "";
      for (const block of blocks) { const ev = block.split("\n").find(x => x.startsWith("event:")); if (ev) setStatus("AI · " + ev.replace("event:", "").trim().replace("run.", "")); }
    }
    setStatus(""); await loadMessages(chatId);
  }
  async function send() {
    if (!selected || !text.trim()) return;
    const outgoing = text; setText(""); setError(null);
    setMessages(m => [...m, {id: Date.now(), sender_name: t("portal.you"), content: outgoing, message_type: "text", created_at: new Date().toISOString()}]);
    try { const j = await (await pfetch(`/portal/chats/${selected}/messages`, {method: "POST", body: JSON.stringify({content: outgoing})})).json(); await streamRun(selected, j.run_id); }
    catch (e) { fail(e, t("portal.send_fail")); setStatus(""); }
  }
  const active = chats.find(c => c.id === selected);
  return <div className="pt-chat">
    <aside className="pt-side">
      <LogoLockup hole="var(--bg)"/>
      <Button size="sm" variant="ghost" onClick={() => { location.href = "/portal"; }}>← {t("portal.back")}</Button>
      <small>{t("portal.ai_conversations")}</small>
      {chats.length ? <div className="ui-list">{chats.map(c => <button key={c.id} type="button" className={"ui-row" + (selected === c.id ? " is-active" : "")} onClick={() => setSelected(c.id)}>
        <span className="ui-ava">{c.agent_name?.[0] || "A"}</span>
        <span className="ui-row-main"><span className="ui-row-title">{c.agent_name}</span><span className="ui-row-meta">{c.title}</span></span></button>)}</div>
        : <p className="ui-empty-line">{t("portal.no_chats")}</p>}
    </aside>
    <main className="pt-chatmain">
      <header className="ui-panel-head"><span className="ui-ava">{active?.agent_name?.[0] || "A"}</span>
        <div className="ui-grow"><h2>{active?.agent_name || t("portal.ai_employee")}</h2><p>{active?.runtime_session_key || t("portal.session_hint")}</p></div></header>
      <div className="pt-messages">
        {messages.length === 0 && <EmptyState mood="chao" title={t("portal.start_with", {p0: active?.agent_name || t("portal.ai_employee")})}>{t("portal.start_desc")}</EmptyState>}
        {messages.map(m => <div key={m.id} className="pt-bubble"><small>{m.sender_name || t("portal.you")}</small><p style={{margin: "4px 0 0", whiteSpace: "pre-wrap"}}>{m.content}</p></div>)}
        {status && <p className="ui-empty-line" role="status">{status}</p>}
      </div>
      <footer className="ui-panel-body" style={{borderTop: "1px solid var(--border)", display: "grid", gap: 8}}>
        {error ? <ErrorBanner error={error} context={errCtx} onClose={() => setError(null)}/> : null}
        <div className="ui-toolbar" style={{flexWrap: "nowrap"}}>
          <textarea className="ui-textarea" rows={2} value={text} onChange={e => setText(e.target.value)} aria-label={t("portal.ask")}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder={t("portal.ask")}/>
          <Button variant="primary" onClick={send} disabled={!text.trim() || !selected}>{t("portal.send")}</Button>
        </div>
      </footer>
    </main>
  </div>;
}
