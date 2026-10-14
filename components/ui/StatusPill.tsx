import type {ReactNode} from "react";

/* Nhãn trạng thái. Tông màu lấy từ token ngữ nghĩa: ok (Rong — xong / agent đang làm),
   wait (Đèn — chờ duyệt), risk (lỗi / bị chặn), info, neutral. */
export type Tone = "ok" | "wait" | "risk" | "info" | "neutral" | "outline";

const STATUS_TONE: Record<string, Tone> = {
  in_progress: "ok", running: "ok", active: "ok", done: "ok", completed: "ok", succeeded: "ok", approved: "ok", healthy: "ok", ready: "ok", matched: "ok",
  review: "wait", pending: "wait", waiting: "wait", queued: "wait", plan_pending: "wait", paused: "wait", warn: "wait", degraded: "wait",
  blocked: "risk", failed: "risk", error: "risk", rejected: "risk", detached: "risk", retired: "neutral", overdue: "risk", fail: "risk",
  backlog: "neutral", todo: "outline", cancelled: "neutral", draft: "neutral", skipped: "neutral",
  resolved: "ok", passed: "ok", success: "ok", enabled: "ok", online: "ok", deployed: "ok", promoted: "ok", verified: "ok", merged: "ok",
  executing: "ok", started: "ok", complete: "ok", clean: "ok", signed: "ok", sent: "ok", delivered: "ok", ok: "ok", green: "ok", on_track: "ok",
  open: "wait", acknowledged: "wait", investigating: "wait", mitigated: "wait", provisioning: "wait", deploying: "wait", planned: "wait",
  waiting_approval: "wait", awaiting_approval: "wait", in_review: "wait", changes_requested: "wait", insufficient_data: "wait", rolled_back: "wait",
  high: "wait", medium: "info", low: "neutral", dirty: "wait", yellow: "wait", at_risk: "wait", scheduled: "info", new: "info",
  breached: "risk", critical: "risk", unhealthy: "risk", offline: "risk", failure: "risk", errored: "risk", red: "risk", off_track: "risk", cleanup_failed: "risk",
  disabled: "neutral", off: "neutral", expired: "neutral", revoked: "neutral", released: "neutral", destroyed: "neutral", closed: "neutral", archived: "neutral",
};
export const toneOf = (status?: string | null): Tone => STATUS_TONE[String(status || "").toLowerCase()] || "neutral";

export function StatusPill({tone = "neutral", children, live, dot = true, title}: {tone?: Tone; children: ReactNode; live?: boolean; dot?: boolean; title?: string}) {
  return <span className={"ui-pill is-" + tone} title={title}>
    {live ? <span className="ui-pulse" aria-hidden="true"/> : dot ? <span className="ui-pill-dot" aria-hidden="true"/> : null}
    {children}
  </span>;
}

export function Count({n, hot}: {n?: number | null; hot?: boolean}) {
  if (!n) return null;
  return <em className={"ui-count" + (hot ? " is-hot" : "")}>{n > 99 ? "99+" : n}</em>;
}
