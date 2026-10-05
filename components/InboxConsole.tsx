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

function ApprovalRow({a, who, onDone}: {a: any; who: string; onDone: (id: number) => void}) {
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
      await apiInbox.resolveApproval(a.id, mode, note.trim());
      onDone(a.id);
      refreshCounts();
    } catch (e: any) {
      setErr(String(e?.message || e).includes("403") ? "Tài khoản này không có quyền duyệt (cần vai trò quản lý)." : "Không gửi được quyết định. Thử lại.");
    } finally { setBusy(false); }
  };

  return <article className="ui-row">
    <span className="ui-row-icon is-waiting"><Icon name="shield" size={16}/></span>
    <div className="ui-row-body">
      <div className="ui-row-title">
        <b>{a.evidence || a.action}</b>
        <span className={"ui-status " + risk.cls}>{risk.label}</span>
      </div>
      <p className="ui-row-meta">
        <code>{a.action}</code><span>·</span><span>{who} gửi</span><span>·</span><span className="ui-mono">#{a.id}</span>
      </p>
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

function NoticeRow({n, onRead}: {n: any; onRead: (id: number) => void}) {
  const unread = n.status === "unread";
  const [busy, setBusy] = useState(false);
  const when = n.created_at ? new Date(n.created_at).toLocaleString("vi-VN", {day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit"}) : "";
  return <article className={"ui-row" + (unread ? " is-unread" : "")}>
    <span className="ui-row-icon"><Icon name={n.item_type === "approval" ? "shield" : n.item_type === "project" ? "layers" : "bell"} size={16}/></span>
    <div className="ui-row-body">
      <div className="ui-row-title"><b>{n.title}</b>{n.priority === "high" && <span className="ui-prio is-high">Cao</span>}</div>
      <p className="ui-row-meta"><span>{n.source || "Hệ thống"}</span>{when && <><span>·</span><span className="ui-mono">{when}</span></>}</p>
    </div>
    {unread && <div className="ui-row-actions">
      <button className="ui-btn is-ghost" disabled={busy} onClick={async () => {
        setBusy(true);
        try { await apiInbox.markRead(n.id); onRead(n.id); refreshCounts(); } catch { setBusy(false); }
      }}>Đánh dấu đã đọc</button>
    </div>}
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
    api.inbox().then((d: any) => setNotices({data: d, error: null})).catch(e => setNotices({data: null, error: String(e)}));
    apiV17.people().then(ps => setPeople(Object.fromEntries(ps.map((p: any) => [p.id, p.name])))).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const pending = approvals.data?.filter(a => a.status === "pending" && !done.includes(a.id)) ?? null;
  const blocked = tasks.data?.filter(t => t.status === "blocked") ?? null;
  const review = tasks.data?.filter(t => t.status === "review") ?? null;
  const sortedNotices = notices.data ? [...notices.data].sort((a, b) =>
    (a.status === "unread" ? 0 : 1) - (b.status === "unread" ? 0 : 1) || String(b.created_at).localeCompare(String(a.created_at))) : null;

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

    <Section title="Thông báo" icon="bell" count={sortedNotices ? sortedNotices.length : null} empty="Chưa có thông báo.">
      {sortedNotices?.map(n => <NoticeRow key={n.id} n={n} onRead={id =>
        setNotices(s => ({...s, data: s.data?.map(x => x.id === id ? {...x, status: "read"} : x) || null}))}/>)}
    </Section>
  </div>;
}
