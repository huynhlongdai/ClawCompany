"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {usePathname, useRouter, useSearchParams} from "next/navigation";
import {Icon} from "./Icon";
import {EmptyState, ErrorState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {apiInboxHub, errorText} from "../lib/api";
import {refreshCounts} from "../lib/counts";

/* M4b — Hộp việc trên một nguồn /api/inbox/items.

   Năm nhóm: Cần anh duyệt · Cần anh xem · Ngân sách · Bài học đề xuất · Thông báo.
   Thẻ duyệt: một chạm "Duyệt" (gửi kèm revision đã xem — nội dung đổi thì máy
   chủ trả 409 và thẻ tự tải lại); "Từ chối" mở lý do có sẵn để chạm. Thiết kế
   cho màn 390px: một cột, nút cao 48px, không bảng. */

type Card = any;

const GROUP_ICON: Record<string, any> = {approvals: "check", review: "pencil", budget: "coins", lessons: "book", updates: "bell"};
const REASONS = ["Chưa đủ thông tin", "Chi phí quá cao", "Để sau", "Sai việc / sai người"];
const SCOPE_VI: Record<string, string> = {task: "Việc này", seat: "Cả seat", department: "Cả phòng"};

function riskCls(r: string) {
  return r === "critical" || r === "high" ? "is-hot" : r === "low" ? "is-low" : "";
}

function ApprovalCard({c, onDone}: {c: Card; onDone: (msg: string, reload?: boolean) => void}) {
  const a = c.approval;
  const [mode, setMode] = useState<"" | "reject">("");
  const [note, setNote] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [scope, setScope] = useState<"task" | "seat" | "department">("task");

  async function send(decision: "approve" | "reject") {
    if (decision === "reject" && !note.trim()) { setErr("Chọn hoặc ghi lý do từ chối để người gửi biết cần sửa gì."); return; }
    setBusy(true); setErr("");
    try {
      const out = await apiInboxHub.decide(a.id, {decision, note: note.trim(), expected_revision: a.revision,
        ...(a.kind === "budget" && decision === "approve" ? {grant_scope: scope} : {})});
      onDone(out?.message || (decision === "approve" ? "Đã duyệt" : "Đã từ chối"));
    } catch (e: any) {
      const code = e?.code || "";
      if (code === "already_decided" || code === "stale_revision") { onDone(errorText(e), true); return; }
      setErr(errorText(e, "Không gửi được quyết định — kiểm tra mạng rồi bấm lại."));
    } finally { setBusy(false); }
  }

  return <article className={"ibx-card is-approval" + (a.overdue ? " is-overdue" : "")} data-testid={`ibx-approval-${a.id}`}>
    <header className="ibx-top">
      <span>{a.kind_vi}{a.requester ? ` · ${a.requester} xin duyệt` : ""}</span>
      <span className={"ibx-risk " + riskCls(a.risk)}>Rủi ro {a.risk_vi.toLowerCase()}</span>
    </header>
    <h3 className="ibx-title">{a.action}</h3>
    {a.summary && <p className="ibx-summary">{a.summary}</p>}
    <div className="ibx-meta">
      {c.department?.name && <span><Icon name="users" size={13}/>{c.department.name}</span>}
      {a.task && <Link href={`/app/work?peek=${a.task.id}`}><Icon name="check" size={13}/>Việc #{a.task.id}</Link>}
      {a.deadline_vi && <span className={a.overdue || a.escalation_blocked ? "is-late" : ""}><Icon name="clock" size={13}/>{a.deadline_vi}</span>}
    </div>
    {!a.can_decide && <p className="ibx-note">Anh chỉ được báo — người duyệt là {a.approver || "quản lý"}.</p>}
    {a.can_decide && a.kind === "budget" && mode !== "reject" &&
      <div className="ibx-scope" role="radiogroup" aria-label="Duyệt chi tiếp cho">
        <small>Cho phép chi tiếp:</small>
        <div className="ui-seg">{(a.grant_scopes || ["task"]).map((s: string) =>
          <button key={s} type="button" role="radio" aria-checked={scope === s} aria-pressed={scope === s}
            onClick={() => setScope(s as any)}>{SCOPE_VI[s] || s}</button>)}</div>
      </div>}
    {a.can_decide && mode === "reject" && <div className="ibx-reject">
      <div className="ui-chips">{REASONS.map(r => <button key={r} type="button" className="ui-chip"
        aria-pressed={note === r} onClick={() => setNote(r)}>{r}</button>)}</div>
      <textarea value={note} onChange={e => setNote(e.target.value)} rows={2} maxLength={2000}
        placeholder="Lý do từ chối (người gửi sẽ đọc)" aria-label="Lý do từ chối"/>
    </div>}
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    {a.can_decide && <div className="ibx-actions">
      {mode === "reject" ? <>
        <button className="ibx-btn is-ghost" disabled={busy} onClick={() => { setMode(""); setErr(""); }}>Quay lại</button>
        <button className="ibx-btn is-danger" disabled={busy} onClick={() => send("reject")}>{busy ? "Đang gửi…" : "Gửi từ chối"}</button>
      </> : <>
        <button className="ibx-btn is-ghost" disabled={busy} onClick={() => setMode("reject")}>Từ chối</button>
        <button className="ibx-btn is-primary" disabled={busy} onClick={() => send("approve")} data-testid={`ibx-approve-${a.id}`}>
          {busy ? "Đang gửi…" : "Duyệt"}</button>
      </>}
    </div>}
  </article>;
}

function NoticeCard({c, onChange}: {c: Card; onChange: (msg?: string) => void}) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  async function mark(status: "read" | "done") {
    if (!c.id) return;
    setBusy(true); setErr("");
    try { await apiInboxHub.setStatus(c.id, status); onChange(); }
    catch (e) { setErr(errorText(e, "Không cập nhật được — thử lại.")); }
    finally { setBusy(false); }
  }
  return <article className={"ibx-card" + (c.status === "unread" ? " is-unread" : "")} data-testid={`ibx-item-${c.id}`}>
    <header className="ibx-top">
      <span>{(c.kinds_vi || []).join(" · ")}{c.count > 1 ? ` · ×${c.count}` : ""}</span>
      {c.priority === "urgent" || c.priority === "high" ? <span className="ibx-risk is-hot">Ưu tiên cao</span> : null}
    </header>
    <h3 className="ibx-title">{c.title}</h3>
    {c.lines?.[0] && <p className="ibx-summary">{c.lines[0]}</p>}
    <div className="ibx-meta">
      {c.seat?.name && <span><Icon name="sparkle" size={13}/>{c.seat.name}</span>}
      {c.department?.name && <span><Icon name="users" size={13}/>{c.department.name}</span>}
      {c.task && <Link href={`/app/work?peek=${c.task.id}`}><Icon name="check" size={13}/>Mở việc #{c.task.id}</Link>}
      {c.related_type === "budget_envelope" && <Link href="/app/costs?tab=budgets"><Icon name="coins" size={13}/>Xem ngân sách</Link>}
    </div>
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    {c.id && <div className="ibx-actions">
      {c.status === "unread" && <button className="ibx-btn is-ghost" disabled={busy} onClick={() => mark("read")}>Đã đọc</button>}
      <button className="ibx-btn is-ghost" disabled={busy} onClick={() => mark("done")}>Xong</button>
    </div>}
  </article>;
}

export function InboxHub() {
  const params = useSearchParams(), router = useRouter(), pathname = usePathname();
  const group = params.get("group") || "";
  const [data, setData] = useState<any>(null), [error, setError] = useState<unknown>(null);
  const toast = useToast(); const setToast = (m: string) => { if (m) toast(m); };
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try { setData(await apiInboxHub.items()); }
    catch (e) { setError(e); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const setGroup = (g: string) => router.replace(g ? `${pathname}?group=${g}` : pathname);
  const after = (msg?: string) => { if (msg) setToast(msg); load(); refreshCounts(); };

  async function readAll() {
    setBusy(true);
    try { const r = await apiInboxHub.readAll(); after(r.updated ? `Đã đánh dấu đọc ${r.updated} mục` : "Không còn mục chưa đọc"); }
    catch (e) { setToast(errorText(e)); } finally { setBusy(false); }
  }
  async function escalate() {
    setBusy(true);
    try { const r = await apiInboxHub.escalate(); after(r.message); }
    catch (e) { setToast(errorText(e)); } finally { setBusy(false); }
  }

  const counts = data?.counts;
  const groups: any[] = (data?.groups || []).filter((g: any) => !group || g.key === group);
  const total = groups.reduce((n, g) => n + g.items.length, 0);

  return <div className="ibx" data-testid="inbox-hub">
    {counts && <div className="ibx-stats" aria-label="Tóm tắt hộp việc">
      <span><b className="ui-num">{counts.by_group.approvals}</b> cần anh duyệt</span>
      <span><b className="ui-num">{counts.by_group.review}</b> cần xem</span>
      {counts.overdue > 0 && <span className="is-late"><b className="ui-num">{counts.overdue}</b> quá hạn</span>}
      <span><b className="ui-num">{counts.unread}</b> chưa đọc</span>
    </div>}
    <div className="ibx-bar">
      <div className="ui-seg ibx-tabs" role="tablist" aria-label="Nhóm">
        <button role="tab" aria-selected={!group} onClick={() => setGroup("")}>Tất cả{counts ? ` ${counts.open}` : ""}</button>
        {(data?.groups || []).map((g: any) => <button key={g.key} role="tab" aria-selected={group === g.key}
          onClick={() => setGroup(g.key)}><Icon name={GROUP_ICON[g.key] || "inbox"} size={14}/>{g.label}
          {counts?.by_group?.[g.key] ? <i className="ui-count">{counts.by_group[g.key]}</i> : null}</button>)}
      </div>
      <div className="ibx-tools">
        <button className="ui-btn is-ghost is-sm" disabled={busy || !counts?.unread} onClick={readAll}>Đọc hết</button>
        {data?.caps?.escalate && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={escalate}
          title="Chuyển các yêu cầu quá hạn lên cấp trên ngay (bình thường hệ thống tự làm mỗi phút)">Leo thang ngay</button>}
      </div>
    </div>

    {error ? <ErrorState error={error} onRetry={load} context="Mở hộp việc"/> : null}
    {!data && !error && <SkeletonRows n={3} h={120}/>}
    {data && !data.linked && <EmptyState mood="chao" title="Tài khoản chưa gắn với một thành viên">
      Hộp việc là của từng người. Nhờ chủ công ty gắn tài khoản của anh với hồ sơ thành viên trong Đội ngũ › Người &amp; quyền.
    </EmptyState>}
    {data && data.linked && total === 0 && <EmptyState mood={group ? "ngu" : "duyet-xong"}
      title={group ? "Nhóm này đang trống" : "Không có gì cần anh lúc này"}>
      {group ? "Chọn “Tất cả” để xem các nhóm khác." : "Bé Càng trông nhà — có phê duyệt, việc chờ xem hay ngân sách chạm nấc sẽ hiện ở đây."}
    </EmptyState>}

    {data && total > 0 && groups.filter(g => g.items.length).map(g => <section key={g.key} className="ibx-group">
      <h2><Icon name={GROUP_ICON[g.key] || "inbox"} size={16}/>{g.label}<span className="ui-num">{g.items.length}</span></h2>
      <div className="ibx-list">{g.items.map((c: Card) => c.approval && c.approval.status === "pending"
        ? <ApprovalCard key={c.key} c={c} onDone={(m, reload) => after(m)}/>
        : <NoticeCard key={c.key} c={c} onChange={m => after(m)}/>)}</div>
    </section>)}
  </div>;
}
