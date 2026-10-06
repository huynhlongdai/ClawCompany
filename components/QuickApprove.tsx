"use client";
// D3.5 — Duyệt nhanh trên điện thoại: một cột thẻ lớn, mỗi thẻ một approval
// đang chờ anh (là người duyệt, hoặc được báo). Nút bấm to, từ chối bắt buộc
// lý do. Không dùng khung ứng dụng đầy đủ để vừa màn hình 360px.
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {AuthGate} from "./AuthGate";
import {apiInbox} from "../lib/api";
import {deadline} from "./InboxConsole";

const RISK_VI: Record<string, [string, string]> = {
  critical: ["Nghiêm trọng", "#b42318"], high: ["Cao", "#c4320a"], medium: ["Vừa", "#b26a00"], low: ["Thấp", "#16794c"],
};

function Card({a, onDone}: {a: any; onDone: (id: number, msg: string) => void}) {
  const [mode, setMode] = useState<"" | "approved" | "rejected">(""), [note, setNote] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [risk, color] = RISK_VI[a.risk] || [a.risk, "#555"];
  async function send() {
    if (mode === "rejected" && !note.trim()) { setErr("Ghi lý do từ chối."); return; }
    setBusy(true); setErr("");
    try { await apiInbox.resolveApproval(a.id, mode as any, note.trim()); onDone(a.id, mode === "approved" ? "Đã duyệt" : "Đã từ chối"); }
    catch (e: any) { setErr(String(e?.message || e).includes("403") ? "Anh không phải người duyệt yêu cầu này." : "Không gửi được, thử lại."); }
    finally { setBusy(false); }
  }
  const big = {flex: 1, minHeight: 52, fontSize: 17, borderRadius: 12, border: "none", fontWeight: 600} as const;
  return <article data-testid={`quick-${a.id}`} style={{background: "#fff", borderRadius: 16, padding: 16, marginBottom: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,.08)", borderLeft: `5px solid ${a.overdue || a.escalated_at ? "#b42318" : color}`}}>
    <div style={{display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13, color: "#666"}}>
      <span>#{a.id} · {a.requester || "hệ thống"} xin duyệt</span><span style={{color, fontWeight: 600}}>Rủi ro {risk}</span>
    </div>
    <div style={{fontSize: 18, fontWeight: 600, margin: "8px 0", lineHeight: 1.35, wordBreak: "break-word"}}>{a.action}</div>
    {a.task && <div style={{fontSize: 14, color: "#444"}}>Việc: <Link href={`/app/tasks/${a.task.id}`}>#{a.task.id} {a.task.title}</Link></div>}
    <div style={{fontSize: 14, marginTop: 6, color: a.overdue ? "#b42318" : "#444"}}>
      {a.expires_at ? deadline(a.expires_at) : "không đặt hạn"}
      {a.escalated_at && <b style={{color: "#b42318"}}> · đã chuyển lên {a.approver || "quản lý"}</b>}
      {!a.is_mine && a.approver && <span> · người duyệt: {a.approver}</span>}
    </div>
    {mode ? <div style={{marginTop: 12}}>
      <textarea rows={3} value={note} onChange={e => setNote(e.target.value)} autoFocus
        placeholder={mode === "approved" ? "Ghi chú (không bắt buộc)" : "Lý do từ chối (bắt buộc)"}
        style={{width: "100%", fontSize: 16, padding: 10, borderRadius: 10, border: "1px solid #ccc", boxSizing: "border-box"}}/>
      {err && <div role="alert" style={{color: "#b42318", fontSize: 14, marginTop: 4}}>{err}</div>}
      <div style={{display: "flex", gap: 10, marginTop: 10}}>
        <button style={{...big, background: "#eee", color: "#333"}} onClick={() => { setMode(""); setErr(""); }} disabled={busy}>Huỷ</button>
        <button style={{...big, background: mode === "approved" ? "#16794c" : "#b42318", color: "#fff"}} onClick={send} disabled={busy}
          data-testid={`quick-confirm-${a.id}`}>{busy ? "Đang gửi…" : mode === "approved" ? "Xác nhận duyệt" : "Xác nhận từ chối"}</button>
      </div>
    </div> : <div style={{display: "flex", gap: 10, marginTop: 14}}>
      <button style={{...big, background: "#fdecea", color: "#b42318"}} onClick={() => setMode("rejected")} data-testid={`quick-reject-${a.id}`}>Từ chối</button>
      <button style={{...big, background: "#16794c", color: "#fff"}} onClick={() => setMode("approved")} data-testid={`quick-approve-${a.id}`}>Duyệt</button>
    </div>}
  </article>;
}

export function QuickApprove() {
  const [items, setItems] = useState<any[] | null>(null), [error, setError] = useState(""), [note, setNote] = useState("");
  const load = useCallback(() => {
    apiInbox.quickApprovals().then((d: any) => setItems(d.approvals)).catch((e: any) => setError(String(e?.message || e)));
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  return <AuthGate><main style={{maxWidth: 520, margin: "0 auto", padding: "16px 12px 40px", background: "#f6f6f3", minHeight: "100vh",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"}}>
    <header style={{display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12}}>
      <div><div style={{fontSize: 22, fontWeight: 700}}>Duyệt nhanh</div>
        <div style={{fontSize: 14, color: "#666"}}>{items === null ? "Đang tải…" : items.length ? `${items.length} yêu cầu đang chờ anh` : "Không có gì chờ anh duyệt."}</div></div>
      <Link href="/app/inbox" style={{fontSize: 14}}>Hộp việc →</Link>
    </header>
    {error && <div role="alert" style={{background: "#fdecea", color: "#b42318", padding: 12, borderRadius: 12, marginBottom: 12}}>{error}</div>}
    {note && <div role="status" style={{background: "#e7f5ee", color: "#16794c", padding: 12, borderRadius: 12, marginBottom: 12}}>{note}</div>}
    {(items || []).map(a => <Card key={a.id} a={a} onDone={(id, msg) => { setItems(s => (s || []).filter(x => x.id !== id)); setNote(`${msg} #${id}.`); }}/>)}
  </main></AuthGate>;
}
