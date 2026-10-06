"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {Icon, IconName} from "./Icon";
import {api, apiInbox, apiV17} from "../lib/api";
import {refreshCounts} from "../lib/counts";

/* Hộp việc — trả lời câu "có cần mình không?" ở một chỗ.

   Bốn nguồn thật: phê duyệt đang chờ (/approvals), nhiệm vụ bị chặn và nhiệm
   vụ chờ duyệt (/v17/workspace/tasks), thông báo (/inbox). Duyệt/từ chối làm
   ngay tại hàng, có bước xác nhận; từ chối bắt buộc ghi lý do để người gửi
   biết sửa gì. */

type Load<T> = {data: T | null; error: string | null};

const RISK: Record<string, {label: string; cls: string}> = {
  critical: {label: "Rủi ro nghiêm trọng", cls: "is-failed"},
  high: {label: "Rủi ro cao", cls: "is-blocked"},
  medium: {label: "Rủi ro vừa", cls: "is-waiting"},
  low: {label: "Rủi ro thấp", cls: "is-done"},
};
const PRIORITY: Record<string, string> = {urgent: "Khẩn", high: "Cao", medium: "Vừa", low: "Thấp"};

function Section({title, count, icon, children, empty}: {
  title: string; count: number | null; icon: IconName; children: React.ReactNode; empty: string;
}) {
  return <section className="ui-section">
    <header className="ui-section-head">
      <Icon name={icon} size={16}/>
      <h2>{title}</h2>
      {count !== null && <span className="ui-num">{count}</span>}
    </header>
    {count === 0 ? <p className="ui-empty-line">{empty}</p> : <div className="ui-list">{children}</div>}
  </section>;
}

/* D1.1 — hàng sinh từ gateway OpenClaw có evidence là JSON (lệnh, thư mục,
   hạn). Bản trước in nguyên khối JSON làm tiêu đề. */
function gatewayRequest(a: any): {command: string; cwd?: string; host?: string; expires?: number} | null {
  if (!String(a.policy_key || "").startsWith("openclaw:")) return null;
  try {
    const ev = JSON.parse(a.evidence || "{}");
    const req = ev?.event?.request || {};
    const command = ev?.command || req.command || "";
    return command ? {command, cwd: ev?.cwd || req.cwd, host: ev?.host || req.host,
                      expires: ev?.expires_at_ms || ev?.event?.expiresAtMs} : null;
  } catch { return null; }
}

function plainEvidence(a: any): string {
  const t = String(a.evidence || "").trim();
  return t && !t.startsWith("{") ? t : a.action;
}

/* D3.5: hạn duyệt; quá hạn thì routine hệ thống chuyển lên quản lý. */
export function deadline(iso: string): string {
  const ms = new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime() - Date.now();
  if (ms <= 0) return "quá hạn — sắp chuyển lên quản lý";
  const h = Math.floor(ms / 3600000), m = Math.floor(ms % 3600000 / 60000);
  return `còn ${h ? h + " giờ " : ""}${m} phút để duyệt`;
}

function ApprovalRow({a, who, onDone}: {a: any; who: string; onDone: (id: number) => void}) {
  const gw = gatewayRequest(a);
  const [notice, setNotice] = useState<string | null>(null);
  const [mode, setMode] = useState<null | "approved" | "rejected">(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const risk = RISK[a.risk] || {label: a.risk, cls: ""};

  const submit = async () => {
    if (!mode) return;
    if (mode === "rejected" && !note.trim()) { setErr("Ghi lý do từ chối để người gửi biết cần sửa gì."); return; }
    setBusy(true); setErr(null);
    try {
      const res: any = await apiInbox.resolveApproval(a.id, mode, note.trim());
      const note_ = String(res?.resolution_note || "");
      if (gw && note_.includes("recorded locally only")) {
        // Quyết định đã ghi nhưng không tới được gateway: nói thẳng, lệnh của agent vẫn đang chờ.
        setNotice("Đã ghi quyết định nhưng chưa gửi được tới OpenClaw — lệnh của agent vẫn đang chờ. "
                  + (note_.match(/\((.*)\)\]?$/)?.[1] || ""));
        setMode(null);
        refreshCounts();
        return;
      }
      onDone(a.id);
      refreshCounts();
    } catch (e: any) {
      const msg = String(e?.message || e);
      setErr(msg.includes("403") ? "Tài khoản này không có quyền duyệt (cần vai trò quản lý)."
        : msg.includes("already") ? "Yêu cầu này đã được quyết định ở nơi khác." : "Không gửi được quyết định. Thử lại.");
    } finally { setBusy(false); }
  };

  return <article className="ui-row">
    <span className="ui-row-icon is-waiting"><Icon name="shield" size={16}/></span>
    <div className="ui-row-body">
      <div className="ui-row-title">
        <b>{gw ? "Agent xin chạy lệnh trên máy chủ OpenClaw" : plainEvidence(a)}</b>
        <span className={"ui-status " + risk.cls}>{risk.label}</span>
      </div>
      {gw && <pre className="ui-mono" data-testid="approval-command" style={{margin: "6px 0", padding: "8px 10px",
        background: "var(--paper-2, #efeee9)", borderRadius: 8, whiteSpace: "pre-wrap", fontSize: 12.5}}>{gw.command}</pre>}
      <p className="ui-row-meta">
        {gw ? <>{gw.cwd && <><span>thư mục <code>{gw.cwd}</code></span><span>·</span></>}
                {gw.expires && <><span>hết hạn {new Date(gw.expires).toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"})}</span><span>·</span></>}</>
            : <><code>{a.action}</code><span>·</span>
                {a.expires_at && <><span>{deadline(a.expires_at)}</span><span>·</span></>}
                {a.escalated_at && <><span className="ui-status is-blocked">đã chuyển lên quản lý</span><span>·</span></>}</>}
        <span>{who} gửi</span><span>·</span><span className="ui-mono">#{a.id}</span>
      </p>
      {notice && <p className="ui-inline-error" role="status" data-testid="approval-notice">{notice}</p>}
      {mode && <div className="ui-confirm">
        <label htmlFor={"note-" + a.id}>{mode === "approved" ? "Ghi chú (không bắt buộc)" : "Lý do từ chối"}</label>
        <textarea id={"note-" + a.id} rows={2} value={note} onChange={e => setNote(e.target.value)} autoFocus
                  placeholder={mode === "approved" ? "Ví dụ: duyệt trong hạn mức tháng 10" : "Ví dụ: cần số liệu ROI của đợt trước"}/>
        {err && <p className="ui-inline-error" role="alert">{err}</p>}
        <div className="ui-confirm-actions">
          <button className={"ui-btn " + (mode === "approved" ? "is-primary" : "is-danger")} onClick={submit} disabled={busy}>
            {busy ? "Đang gửi…" : mode === "approved" ? "Xác nhận duyệt" : "Xác nhận từ chối"}
          </button>
          <button className="ui-btn is-ghost" onClick={() => { setMode(null); setErr(null); }} disabled={busy}>Huỷ</button>
        </div>
      </div>}
    </div>
    {!mode && <div className="ui-row-actions">
      <button className="ui-btn is-ghost" onClick={() => setMode("rejected")}>Từ chối</button>
      <button className="ui-btn is-primary" onClick={() => setMode("approved")}><Icon name="check" size={14}/>Duyệt</button>
    </div>}
  </article>;
}

function TaskRow({t, tone}: {t: any; tone: "blocked" | "review"}) {
  return <Link href={`/app/tasks/${t.id}`} className="ui-row is-link">
    <span className={"ui-row-icon is-" + tone}><Icon name={tone === "blocked" ? "alert" : "check"} size={16}/></span>
    <div className="ui-row-body">
      <div className="ui-row-title"><b>{t.title}</b>
        {t.priority && <span className={"ui-prio is-" + t.priority}>{PRIORITY[t.priority] || t.priority}</span>}
      </div>
      <p className="ui-row-meta">
        <span>{t.project_name || "Không có dự án"}</span><span>·</span>
        <span>{t.assignee_name || "Chưa giao"}{t.assignee_type === "agent" ? " (agent)" : ""}</span><span>·</span>
        <span className="ui-mono">#{t.id}</span>
      </p>
    </div>
    <span className="ui-row-go"><Icon name="arrow-right" size={15}/></span>
  </Link>;
}

/* D3.5 — mỗi việc một dòng: các báo cho cùng task (chờ duyệt, run lỗi, vào
   review, được nhắc tên, ngân sách) gộp lại, có số lần và vài dòng gần nhất. */
function NoticeRow({n, onRead}: {n: any; onRead: (id: number) => void}) {
  const unread = n.status === "unread";
  const [busy, setBusy] = useState(false), [open, setOpen] = useState(false);
  const at = n.updated_at || n.created_at;
  const when = at ? new Date(at + (String(at).endsWith("Z") ? "" : "Z")).toLocaleString("vi-VN", {day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit"}) : "";
  const lines: string[] = n.lines || [];
  return <article className={"ui-row" + (unread ? " is-unread" : "")} data-testid={`inbox-item-${n.id}`}>
    <span className="ui-row-icon"><Icon name={String(n.kind).startsWith("approval") ? "shield" : n.kind === "run_failed" ? "alert" : "bell"} size={16}/></span>
    <div className="ui-row-body">
      <div className="ui-row-title"><b>{n.title}</b>
        {n.count > 1 && <span className="ui-num" title="Số báo đã gộp">×{n.count}</span>}
        {(n.priority === "high" || n.priority === "urgent") && <span className="ui-prio is-high">{n.priority === "urgent" ? "Khẩn" : "Cao"}</span>}
      </div>
      <p className="ui-row-meta">
        {(n.kinds_vi || []).map((k: string) => <span key={k} className="ui-status">{k}</span>)}
        {n.task_id && <><span>·</span><Link href={`/app/tasks/${n.task_id}`}>task #{n.task_id}</Link></>}
        {when && <><span>·</span><span className="ui-mono">{when}</span></>}
        {lines.length > 1 && <><span>·</span><button className="ui-btn is-ghost" style={{padding: "0 6px"}} onClick={() => setOpen(!open)}>{open ? "Thu gọn" : `${lines.length} dòng`}</button></>}
      </p>
      {(open ? lines : lines.slice(0, 1)).map((l, i) => <p key={i} className="ui-row-meta" style={{margin: 0}}>{l}</p>)}
    </div>
    <div className="ui-row-actions">
      {unread && <button className="ui-btn is-ghost" disabled={busy} onClick={async () => {
        setBusy(true);
        try { await apiInbox.setStatus(n.id, "read"); onRead(n.id); refreshCounts(); } catch { /* giữ nguyên */ } finally { setBusy(false); }
      }}>Đã đọc</button>}
      <button className="ui-btn is-ghost" disabled={busy} onClick={async () => {
        setBusy(true);
        try { await apiInbox.setStatus(n.id, "done"); onRead(-n.id); refreshCounts(); } catch { /* giữ nguyên */ } finally { setBusy(false); }
      }}>Xong</button>
    </div>
  </article>;
}

export function InboxConsole() {
  const [approvals, setApprovals] = useState<Load<any[]>>({data: null, error: null});
  const [tasks, setTasks] = useState<Load<any[]>>({data: null, error: null});
  const [notices, setNotices] = useState<Load<any[]>>({data: null, error: null});
  const [people, setPeople] = useState<Record<number, string>>({});
  const [done, setDone] = useState<number[]>([]);

  const load = useCallback(() => {
    api.approvals().then((d: any) => setApprovals({data: d, error: null})).catch(e => setApprovals({data: null, error: String(e)}));
    apiV17.tasks().then(d => setTasks({data: d, error: null})).catch(e => setTasks({data: null, error: String(e)}));
    apiInbox.mine().then((d: any) => setNotices({data: d.items, error: null})).catch(e => setNotices({data: null, error: String(e)}));
    apiV17.people().then(ps => setPeople(Object.fromEntries(ps.map((p: any) => [p.id, p.name])))).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const pending = approvals.data?.filter(a => a.status === "pending" && !done.includes(a.id)) ?? null;
  const blocked = tasks.data?.filter(t => t.status === "blocked") ?? null;
  const review = tasks.data?.filter(t => t.status === "review") ?? null;
  const sortedNotices = notices.data ? [...notices.data].sort((a, b) =>
    (a.status === "unread" ? 0 : 1) - (b.status === "unread" ? 0 : 1) || String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at))) : null;

  const loading = approvals.data === null && !approvals.error;
  const anyError = approvals.error || tasks.error || notices.error;
  const total = (pending?.length || 0) + (blocked?.length || 0) + (review?.length || 0);

  if (loading) return <div className="ui-stack"><div className="ui-skel" style={{height: 64}}/><div className="ui-skel" style={{height: 180}}/><div className="ui-skel" style={{height: 120}}/></div>;

  return <div className="ui-stack ui-inbox">
    {anyError && <div className="ui-banner is-error" role="alert">
      <Icon name="alert" size={16}/>
      <span>Một phần Hộp việc không tải được. Các mục bên dưới có thể thiếu.</span>
      <button className="ui-btn is-ghost" onClick={load}>Tải lại</button>
    </div>}

    <div className="ui-summary">
      <b className="ui-num-lg">{total}</b>
      <span>{total === 0 ? "Không có gì đang chờ anh. Đội đang tự chạy." : "việc đang chờ anh quyết hoặc gỡ"}</span>
    </div>

    <Section title="Cần anh duyệt" icon="shield" count={pending ? pending.length : null} empty="Không có phê duyệt nào đang chờ.">
      {pending?.map(a => <ApprovalRow key={a.id} a={a} who={people[a.requester_member_id] || `Thành viên #${a.requester_member_id}`}
                                      onDone={id => setDone(d => [...d, id])}/>)}
    </Section>

    <Section title="Bị chặn" icon="alert" count={blocked ? blocked.length : null} empty="Không có nhiệm vụ nào bị chặn.">
      {blocked?.map(t => <TaskRow key={t.id} t={t} tone="blocked"/>)}
    </Section>

    <Section title="Chờ duyệt kết quả" icon="check" count={review ? review.length : null} empty="Không có kết quả nào chờ duyệt.">
      {review?.map(t => <TaskRow key={t.id} t={t} tone="review"/>)}
    </Section>

    <Section title="Thông báo theo việc" icon="bell" count={sortedNotices ? sortedNotices.length : null} empty="Chưa có thông báo.">
      {sortedNotices?.map(n => <NoticeRow key={n.id} n={n} onRead={id =>
        setNotices(s => ({...s, data: id < 0 ? (s.data?.filter(x => x.id !== -id) || null)
          : (s.data?.map(x => x.id === id ? {...x, status: "read"} : x) || null)}))}/>)}
    </Section>
    <p className="ui-row-meta"><Link href="/app/approve">Mở màn duyệt nhanh (điện thoại) →</Link></p>
  </div>;
}
