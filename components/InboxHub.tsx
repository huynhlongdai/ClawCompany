"use client";
import {riskLabel} from "@/lib/risk";
import {kindLabel, deadlineText} from "@/lib/approvalText";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {usePathname, useRouter, useSearchParams} from "next/navigation";
import {Icon} from "./Icon";
import {EmptyState, ErrorState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {apiInboxHub, errorText} from "../lib/api";
import {refreshCounts} from "../lib/counts";
import {t, lazy} from "../lib/i18n";

/* M4b — Hộp việc trên một nguồn /api/inbox/items.

   Năm nhóm: Cần anh duyệt · Cần anh xem · Ngân sách · Bài học đề xuất · Thông báo.
   Thẻ duyệt: một chạm "Duyệt" (gửi kèm revision đã xem — nội dung đổi thì máy
   chủ trả 409 và thẻ tự tải lại); "Từ chối" mở lý do có sẵn để chạm. Thiết kế
   cho màn 390px: một cột, nút cao 48px, không bảng. */

type Card = any;

const GROUP_ICON: Record<string, any> = {approvals: "check", review: "pencil", budget: "coins", lessons: "book", updates: "bell"};
const REASONS = lazy(() => ([t("inbox.chua_du_thong_tin"), t("inbox.chi_phi_qua_cao"), t("inbox.de_sau"), t("inbox.sai_viec_sai_nguoi")]));
const SCOPE_VI: Record<string, string> = lazy(() => ({task: t("inbox.viec_nay"), seat: t("inbox.ca_seat"), department: t("inbox.ca_phong")}));

function riskCls(r: string) {
  return r === "critical" || r === "high" ? "is-hot" : r === "low" ? "is-low" : "";
}

function ApprovalCard({c, onDone}: {c: Card; onDone: (msg: string, reload?: boolean) => void}) {
  const a = c.approval;
  const [mode, setMode] = useState<"" | "reject">("");
  const [note, setNote] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [scope, setScope] = useState<"task" | "seat" | "department">("task");
  const [open, setOpen] = useState(false), [det, setDet] = useState<any>(null), [detErr, setDetErr] = useState("");
  async function toggle() {
    const next = !open; setOpen(next);
    if (next && !det) {
      setDetErr("");
      try { setDet(await apiInboxHub.approval(a.id)); } catch (e) { setDetErr(errorText(e, t("inbox.khong_tai_duoc_chi_tiet"))); }
    }
  }

  async function send(decision: "approve" | "reject") {
    if (decision === "reject" && !note.trim()) { setErr(t("inbox.chon_hoac_ghi_ly_do")); return; }
    setBusy(true); setErr("");
    try {
      const out = await apiInboxHub.decide(a.id, {decision, note: note.trim(), expected_revision: a.revision,
        ...(a.kind === "budget" && decision === "approve" ? {grant_scope: scope} : {})});
      onDone(out?.message || (decision === "approve" ? t("inbox.da_duyet") : t("inbox.da_tu_choi")));
    } catch (e: any) {
      const code = e?.code || "";
      if (code === "already_decided" || code === "stale_revision") { onDone(errorText(e), true); return; }
      setErr(errorText(e, t("inbox.khong_gui_duoc_quyet_dinh")));
    } finally { setBusy(false); }
  }

  return <article className={"ibx-card is-approval" + (a.overdue ? " is-overdue" : "")} data-testid={`ibx-approval-${a.id}`}>
    <header className="ibx-top">
      <span>{kindLabel(a.kind)}{a.requester ? t("inbox.xin_duyet", {p0: a.requester}) : ""}</span>
      <span className={"ibx-risk " + riskCls(a.risk)}>{riskLabel(a.risk)}</span>
    </header>
    <h3 className="ibx-title"><button type="button" className="ibx-title-btn" onClick={toggle} aria-expanded={open}>{a.action}</button></h3>
    {a.summary && !open && <p className="ibx-summary">{a.summary}</p>}
    <button type="button" className="ibx-more" onClick={toggle} aria-expanded={open} data-testid={`ibx-detail-toggle-${a.id}`}>
      <Icon name={open ? "chevron-down" : "chevron-right"} size={14}/>{open ? t("inbox.an_chi_tiet") : t("inbox.xem_chi_tiet")}</button>
    {open && <ApprovalDetail det={det} err={detErr}/>}
    <div className="ibx-meta">
      {c.department?.name && <span><Icon name="users" size={13}/>{c.department.name}</span>}
      {a.task && <Link href={`/app/work?peek=${a.task.id}`}><Icon name="check" size={13}/>{t("inbox.viec")}{a.task.id}</Link>}
      {deadlineText(a) && <span className={a.overdue || a.escalation_blocked ? "is-late" : ""}><Icon name="clock" size={13}/>{deadlineText(a)}</span>}
    </div>
    {!a.can_decide && <p className="ibx-note">{t("inbox.anh_chi_duoc_bao_nguoi")} {a.approver || t("inbox.quan_ly")}.</p>}
    {a.can_decide && a.kind === "budget" && mode !== "reject" &&
      <div className="ibx-scope" role="radiogroup" aria-label={t("inbox.duyet_chi_tiep_cho")}>
        <small>{t("inbox.cho_phep_chi_tiep")}</small>
        <div className="ui-seg">{(a.grant_scopes || ["task"]).map((s: string) =>
          <button key={s} type="button" role="radio" aria-checked={scope === s} aria-pressed={scope === s}
            onClick={() => setScope(s as any)}>{SCOPE_VI[s] || s}</button>)}</div>
      </div>}
    {a.can_decide && mode === "reject" && <div className="ibx-reject">
      <div className="ui-chips">{REASONS.map(r => <button key={r} type="button" className="ui-chip"
        aria-pressed={note === r} onClick={() => setNote(r)}>{r}</button>)}</div>
      <textarea value={note} onChange={e => setNote(e.target.value)} rows={2} maxLength={2000}
        placeholder={t("inbox.ly_do_tu_choi_nguoi")} aria-label={t("inbox.ly_do_tu_choi")}/>
    </div>}
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    {a.can_decide && <div className="ibx-actions">
      {mode === "reject" ? <>
        <button className="ibx-btn is-ghost" disabled={busy} onClick={() => { setMode(""); setErr(""); }}>{t("inbox.quay_lai")}</button>
        <button className="ibx-btn is-danger" disabled={busy} onClick={() => send("reject")}>{busy ? t("inbox.dang_gui") : t("inbox.gui_tu_choi")}</button>
      </> : <>
        <button className="ibx-btn is-ghost" disabled={busy} onClick={() => setMode("reject")}>{t("inbox.tu_choi")}</button>
        <button className="ibx-btn is-primary" disabled={busy} onClick={() => send("approve")} data-testid={`ibx-approve-${a.id}`}>
          {busy ? t("inbox.dang_gui") : t("inbox.duyet")}</button>
      </>}
    </div>}
  </article>;
}

function fmtTime(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function ApprovalDetail({det, err}: {det: any; err: string}) {
  if (err) return <p className="ui-inline-error" role="alert">{err}</p>;
  if (!det) return <SkeletonRows n={2} h={40}/>;
  const td = det.task_detail;
  return <div className="ibx-detail" data-testid={`ibx-detail-${det.id}`}>
    <dl className="ibx-dl">
      <dt>{t("inbox.loai_yeu_cau")}</dt><dd>{det.kind_vi}</dd>
      {det.requester_detail && <><dt>{t("inbox.nguoi_xin")}</dt>
        <dd>{det.requester_detail.name}{det.requester_detail.type === "agent" ? ` · ${t("inbox.agent")}` : ""}</dd></>}
      {det.approver && <><dt>{t("inbox.nguoi_duyet_nhan")}</dt><dd>{det.approver}</dd></>}
      {det.created_at && <><dt>{t("inbox.gui_luc")}</dt><dd>{fmtTime(det.created_at)}</dd></>}
      {det.expires_at && <><dt>{t("inbox.han_duyet")}</dt><dd>{fmtTime(det.expires_at)}</dd></>}
      {det.fields.map((f: any, i: number) => <div key={i} className="ibx-dl-row">
        <dt>{f.label}</dt><dd>{f.mono ? <code className="ibx-code">{f.value}</code> : <span className="ibx-pre">{f.value}</span>}</dd></div>)}
    </dl>
    {det.text && <p className="ibx-pre">{det.text}</p>}
    {!det.fields.length && !det.text && <p className="ibx-note">{t("inbox.khong_co_mo_ta_them")}</p>}
    {td && <div className="ibx-task">
      <b>{t("inbox.viec")}{td.id}: {td.title}</b>
      <small>{[td.project, td.assignee, td.status].filter(Boolean).join(" · ")}</small>
      {td.description && <p className="ibx-pre">{td.description}</p>}
      <Link href={`/app/work?peek=${td.id}`}>{t("inbox.mo_viec")}{td.id}</Link>
    </div>}
  </div>;
}

function NoticeCard({c, onChange}: {c: Card; onChange: (msg?: string) => void}) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  async function mark(status: "read" | "done") {
    if (!c.id) return;
    setBusy(true); setErr("");
    try { await apiInboxHub.setStatus(c.id, status); onChange(); }
    catch (e) { setErr(errorText(e, t("inbox.khong_cap_nhat_duoc_thu"))); }
    finally { setBusy(false); }
  }
  return <article className={"ibx-card" + (c.status === "unread" ? " is-unread" : "")} data-testid={`ibx-item-${c.id}`}>
    <header className="ibx-top">
      <span>{(c.kinds_vi || []).join(" · ")}{c.count > 1 ? ` · ×${c.count}` : ""}</span>
      {c.priority === "urgent" || c.priority === "high" ? <span className="ibx-risk is-hot">{t("inbox.uu_tien_cao")}</span> : null}
    </header>
    <h3 className="ibx-title">{c.title}</h3>
    {c.lines?.[0] && <p className="ibx-summary">{c.lines[0]}</p>}
    <div className="ibx-meta">
      {c.seat?.name && <span><Icon name="sparkle" size={13}/>{c.seat.name}</span>}
      {c.department?.name && <span><Icon name="users" size={13}/>{c.department.name}</span>}
      {c.task && <Link href={`/app/work?peek=${c.task.id}`}><Icon name="check" size={13}/>{t("inbox.mo_viec")}{c.task.id}</Link>}
      {c.related_type === "budget_envelope" && <Link href="/app/costs?tab=budgets"><Icon name="coins" size={13}/>{t("inbox.xem_ngan_sach")}</Link>}
    </div>
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    {c.id && <div className="ibx-actions">
      {c.status === "unread" && <button className="ibx-btn is-ghost" disabled={busy} onClick={() => mark("read")}>{t("inbox.da_doc")}</button>}
      <button className="ibx-btn is-ghost" disabled={busy} onClick={() => mark("done")}>{t("inbox.xong")}</button>
    </div>}
  </article>;
}

/* Tên nhóm theo ngôn ngữ (backend trả nhãn tiếng Việt cố định; khoá nhóm là id ổn định). */
const GROUP_KEYS = ["approvals", "review", "budget", "lessons", "updates"] as const;
function groupLabel(g: {key: string; label: string}) {
  return (GROUP_KEYS as readonly string[]).includes(g.key) ? t(`inbox.nhom_${g.key}` as any) : g.label;
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
    try { const r = await apiInboxHub.readAll(); after(r.updated ? t("inbox.da_danh_dau_doc_muc", {p0: r.updated}) : t("inbox.khong_con_muc_chua_doc")); }
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
    {counts && <div className="ibx-stats" aria-label={t("inbox.tom_tat_hop_viec")}>
      <span><b className="ui-num">{counts.by_group.approvals}</b> {t("inbox.can_anh_duyet")}</span>
      <span><b className="ui-num">{counts.by_group.review}</b> {t("inbox.can_xem")}</span>
      {counts.overdue > 0 && <span className="is-late"><b className="ui-num">{counts.overdue}</b> {t("inbox.qua_han")}</span>}
      <span><b className="ui-num">{counts.unread}</b> {t("inbox.chua_doc")}</span>
    </div>}
    <div className="ibx-bar">
      <div className="ui-seg ibx-tabs" role="tablist" aria-label={t("inbox.nhom")}>
        <button role="tab" aria-selected={!group} onClick={() => setGroup("")}>{t("inbox.tat_ca")}{counts ? ` ${counts.open}` : ""}</button>
        {(data?.groups || []).map((g: any) => <button key={g.key} role="tab" aria-selected={group === g.key}
          onClick={() => setGroup(g.key)}><Icon name={GROUP_ICON[g.key] || "inbox"} size={14}/>{groupLabel(g)}
          {counts?.by_group?.[g.key] ? <i className="ui-count">{counts.by_group[g.key]}</i> : null}</button>)}
      </div>
      <div className="ibx-tools">
        <button className="ui-btn is-ghost is-sm" disabled={busy || !counts?.unread} onClick={readAll}>{t("inbox.doc_het")}</button>
        {data?.caps?.escalate && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={escalate}
          title={t("inbox.chuyen_cac_yeu_cau_qua")}>{t("inbox.leo_thang_ngay")}</button>}
      </div>
    </div>

    {error ? <ErrorState error={error} onRetry={load} context={t("inbox.mo_hop_viec")}/> : null}
    {!data && !error && <SkeletonRows n={3} h={120}/>}
    {data && !data.linked && <EmptyState mood="chao" title={t("inbox.tai_khoan_chua_gan_voi")}>
      {t("inbox.hop_viec_la_cua_tung")}
    </EmptyState>}
    {data && data.linked && total === 0 && <EmptyState mood={group ? "ngu" : "duyet-xong"}
      title={group ? t("inbox.nhom_nay_dang_trong") : t("inbox.khong_co_gi_can_anh")}>
      {group ? t("inbox.chon_tat_ca_de_xem") : t("inbox.be_cang_trong_nha_co")}
    </EmptyState>}

    {data && total > 0 && groups.filter(g => g.items.length).map(g => <section key={g.key} className="ibx-group">
      <h2><Icon name={GROUP_ICON[g.key] || "inbox"} size={16}/>{groupLabel(g)}<span className="ui-num">{g.items.length}</span></h2>
      <div className="ibx-list">{g.items.map((c: Card) => c.approval && c.approval.status === "pending"
        ? <ApprovalCard key={c.key} c={c} onDone={(m, reload) => after(m)}/>
        : <NoticeCard key={c.key} c={c} onChange={m => after(m)}/>)}</div>
    </section>)}
  </div>;
}
