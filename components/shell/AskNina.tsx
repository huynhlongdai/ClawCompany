"use client";
import {FormEvent, useEffect, useRef, useState} from "react";
import {Sheet} from "../ui/Dialog";
import {Button} from "../ui/Button";
import {API_BASE} from "../../lib/http";
import {getLocale, t} from "../../lib/i18n";

/* Hỏi Nina, trả lời chảy ra từng đoạn (SSE qua fetch POST).
   Bài học từ FastClaw: thấy chữ đầu tiên sớm quan trọng hơn tổng thời gian.
   Mỗi `delta` mang TOÀN VĂN tới lúc đó nên chỉ cần thay, mất một frame không lệch. */
type Turn = {q: string; a: string; tool?: string; err?: string; timing?: string; done?: boolean};

export async function* readSse(res: Response): AsyncGenerator<{event: string; data: any}> {
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream: true});
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      let event = "message", data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      try { yield {event, data: JSON.parse(data)}; } catch { /* frame hỏng: bỏ qua */ }
    }
  }
}

export function AskNina({onClose}: {onClose: () => void}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({block: "end"}); }, [turns]);
  useEffect(() => () => abort.current?.abort(), []);

  const patch = (p: Partial<Turn>) => setTurns(ts => ts.map((x, i) => i === ts.length - 1 ? {...x, ...p} : x));

  async function ask(e: FormEvent) {
    e.preventDefault();
    const message = q.trim();
    if (!message || busy) return;
    setQ(""); setBusy(true);
    setTurns(ts => [...ts, {q: message, a: ""}]);
    const ctrl = new AbortController(); abort.current = ctrl;
    try {
      const token = localStorage.getItem("clawcompany_token");
      const res = await fetch(`${API_BASE}/v36/nina/ask/stream`, {
        method: "POST", signal: ctrl.signal, cache: "no-store",
        headers: {"Content-Type": "application/json", "Accept-Language": getLocale(),
                  ...(token ? {Authorization: `Bearer ${token}`} : {})},
        body: JSON.stringify({message, timeout_seconds: 120}),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      for await (const {event, data} of readSse(res)) {
        if (event === "delta") patch({a: data.text, tool: undefined});
        else if (event === "tool") patch({tool: data.title || data.name});
        else if (event === "final") patch({a: data.reply, done: true, tool: undefined,
          timing: t("shell.tra_loi_sau", {p0: data.first_token_seconds ?? "–", p1: data.elapsed_seconds})});
        else if (event === "error") patch({err: data.message, a: data.partial || "", done: true});
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") patch({err: String(err?.message || err), done: true});
    } finally {
      setBusy(false); abort.current = null;
      patch({done: true, tool: undefined});
    }
  }

  return <Sheet label={t("shell.hoi_nina")} onClose={onClose} testId="ask-nina"
                head={<strong>{t("shell.hoi_nina")}</strong>}>
    <div style={{display: "flex", flexDirection: "column", gap: 14, minHeight: "100%"}}>
      {turns.map((x, i) => <div key={i} style={{display: "flex", flexDirection: "column", gap: 6}}>
        <div style={{alignSelf: "flex-end", maxWidth: "85%", background: "var(--surface-2)",
                     padding: "8px 12px", borderRadius: 12}}>{x.q}</div>
        <div data-testid="ask-nina-answer" style={{whiteSpace: "pre-wrap", lineHeight: 1.55}}>
          {x.a || (!x.done && !x.err ? <span style={{color: "var(--text-muted)"}}>{x.tool ? t("shell.dang_dung_tool", {p0: x.tool}) : t("shell.dang_nghi")}</span> : null)}
        </div>
        {x.tool && x.a && <span style={{fontSize: 12, color: "var(--text-muted)"}}>{t("shell.dang_dung_tool", {p0: x.tool})}</span>}
        {x.err && <div role="alert" style={{color: "var(--risk)", fontSize: 13}}>{t("shell.loi_hoi_nina", {p0: x.err})}</div>}
        {x.timing && <span style={{fontSize: 12, color: "var(--text-muted)"}} data-testid="ask-nina-timing">{x.timing}</span>}
      </div>)}
      <div ref={end}/>
      <form onSubmit={ask} style={{display: "flex", gap: 8, marginTop: "auto", position: "sticky", bottom: 0,
                                   background: "var(--surface)", paddingTop: 8}}>
        <input className="ui-input" style={{flex: 1}} value={q} onChange={e => setQ(e.target.value)} autoFocus
               placeholder={t("shell.hoi_nina_placeholder")} maxLength={4000} data-testid="ask-nina-input"/>
        {busy ? <Button type="button" onClick={() => abort.current?.abort()}>{t("shell.dung")}</Button>
              : <Button type="submit" variant="primary" disabled={!q.trim()}>{t("shell.gui")}</Button>}
      </form>
    </div>
  </Sheet>;
}
