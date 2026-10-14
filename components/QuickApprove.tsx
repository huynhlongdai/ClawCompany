"use client";
// D3.5 — Duyệt nhanh trên điện thoại: một cột thẻ lớn, mỗi thẻ một approval
// đang chờ anh (là người duyệt, hoặc được báo). Nút bấm to, từ chối bắt buộc
// lý do. Không dùng khung ứng dụng đầy đủ để vừa màn hình 360px.
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {apiInbox} from "../lib/api";
import {deadline} from "./InboxConsole";
import {t as tr, lazy} from "../lib/i18n";

const RISK_VI: Record<string, [string, string]> = lazy(() => ({
  critical: [tr("inbox.nghiem_trong"), "#b42318"], high: ["Cao", "#c4320a"], medium: [tr("inbox.vua"), "#b26a00"], low: [tr("inbox.thap"), "#16794c"],
}));

function Card({a, onDone}: {a: any; onDone: (id: number, msg: string) => void}) {
  const [mode, setMode] = useState<"" | "approved" | "rejected">(""), [note, setNote] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [risk, color] = RISK_VI[a.risk] || [a.risk, "#555"];
  async function send() {
    if (mode === "rejected" && !note.trim()) { setErr(tr("inbox.ghi_ly_do_tu_choi")); return; }
    setBusy(true); setErr("");
    try { await apiInbox.resolveApproval(a.id, mode as any, note.trim()); onDone(a.id, mode === "approved" ? tr("inbox.da_duyet") : tr("inbox.da_tu_choi")); }
    catch (e: any) { setErr(String(e?.message || e).includes("403") ? tr("inbox.anh_khong_phai_nguoi_duyet") : tr("inbox.khong_gui_duoc_thu_lai")); }
    finally { setBusy(false); }
  }
  const big = {flex: 1, minHeight: 52, fontSize: 17, borderRadius: 12, border: "none", fontWeight: 600} as const;
  return <article data-testid={`quick-${a.id}`} style={{background: "#fff", borderRadius: 16, padding: 16, marginBottom: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,.08)", borderLeft: `5px solid ${a.overdue || a.escalated_at ? "#b42318" : color}`}}>
    <div style={{display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13, color: "#666"}}>
      <span>#{a.id} · {a.requester || tr("inbox.he_thong")} {tr("inbox.xin_duyet_2")}</span><span style={{color, fontWeight: 600}}>{tr("inbox.rui_ro")} {risk}</span>
    </div>
    <div style={{fontSize: 18, fontWeight: 600, margin: "8px 0", lineHeight: 1.35, wordBreak: "break-word"}}>{a.action}</div>
    {a.task && <div style={{fontSize: 14, color: "#444"}}>{tr("inbox.viec_2")} <Link href={`/app/tasks/${a.task.id}`}>#{a.task.id} {a.task.title}</Link></div>}
    <div style={{fontSize: 14, marginTop: 6, color: a.overdue ? "#b42318" : "#444"}}>
      {a.expires_at ? deadline(a.expires_at) : tr("inbox.khong_dat_han")}
      {a.escalated_at && <b style={{color: "#b42318"}}> {tr("inbox.da_chuyen_len")} {a.approver || tr("inbox.quan_ly")}</b>}
      {!a.is_mine && a.approver && <span> {tr("inbox.nguoi_duyet")} {a.approver}</span>}
    </div>
    {mode ? <div style={{marginTop: 12}}>
      <textarea rows={3} value={note} onChange={e => setNote(e.target.value)} autoFocus
        placeholder={mode === "approved" ? tr("inbox.ghi_chu_khong_bat_buoc") : tr("inbox.ly_do_tu_choi_bat")}
        style={{width: "100%", fontSize: 16, padding: 10, borderRadius: 10, border: "1px solid #ccc", boxSizing: "border-box"}}/>
      {err && <div role="alert" style={{color: "#b42318", fontSize: 14, marginTop: 4}}>{err}</div>}
      <div style={{display: "flex", gap: 10, marginTop: 10}}>
        <button style={{...big, background: "#eee", color: "#333"}} onClick={() => { setMode(""); setErr(""); }} disabled={busy}>{tr("inbox.huy")}</button>
        <button style={{...big, background: mode === "approved" ? "#16794c" : "#b42318", color: "#fff"}} onClick={send} disabled={busy}
          data-testid={`quick-confirm-${a.id}`}>{busy ? tr("inbox.dang_gui") : mode === "approved" ? tr("inbox.xac_nhan_duyet") : tr("inbox.xac_nhan_tu_choi")}</button>
      </div>
    </div> : <div style={{display: "flex", gap: 10, marginTop: 14}}>
      <button style={{...big, background: "#fdecea", color: "#b42318"}} onClick={() => setMode("rejected")} data-testid={`quick-reject-${a.id}`}>{tr("inbox.tu_choi")}</button>
      <button style={{...big, background: "#16794c", color: "#fff"}} onClick={() => setMode("approved")} data-testid={`quick-approve-${a.id}`}>{tr("inbox.duyet")}</button>
    </div>}
  </article>;
}

export function QuickApprove() {
  const [items, setItems] = useState<any[] | null>(null), [error, setError] = useState(""), [note, setNote] = useState("");
  const load = useCallback(() => {
    apiInbox.quickApprovals().then((d: any) => setItems(d.approvals)).catch((e: any) => setError(String(e?.message || e)));
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  return <main style={{maxWidth: 520, margin: "0 auto", padding: "16px 12px 40px", background: "#f6f6f3", minHeight: "100vh",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"}}>
    <header style={{display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12}}>
      <div><div style={{fontSize: 22, fontWeight: 700}}>{tr("inbox.duyet_nhanh")}</div>
        <div style={{fontSize: 14, color: "#666"}}>{items === null ? tr("inbox.dang_tai") : items.length ? tr("inbox.yeu_cau_dang_cho_anh", {p0: items.length}) : tr("inbox.khong_co_gi_cho_anh")}</div></div>
      <Link href="/app/inbox" style={{fontSize: 14}}>{tr("inbox.hop_viec")}</Link>
    </header>
    {error && <div role="alert" style={{background: "#fdecea", color: "#b42318", padding: 12, borderRadius: 12, marginBottom: 12}}>{error}</div>}
    {note && <div role="status" style={{background: "#e7f5ee", color: "#16794c", padding: 12, borderRadius: 12, marginBottom: 12}}>{note}</div>}
    {(items || []).map(a => <Card key={a.id} a={a} onDone={(id, msg) => { setItems(s => (s || []).filter(x => x.id !== id)); setNote(`${msg} #${id}.`); }}/>)}
  </main>;
}
