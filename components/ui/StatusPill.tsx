import type {ReactNode} from "react";

/* Nhãn trạng thái. Tông màu lấy từ token ngữ nghĩa: ok (Rong — xong / agent đang làm),
   wait (Đèn — chờ duyệt), risk (lỗi / bị chặn), info, neutral. */
export type Tone = "ok" | "wait" | "risk" | "info" | "neutral" | "outline";

const STATUS_TONE: Record<string, Tone> = {
  in_progress: "ok", running: "ok", active: "ok", done: "ok", completed: "ok", succeeded: "ok", approved: "ok", healthy: "ok", ready: "ok", matched: "ok",
  review: "wait", pending: "wait", waiting: "wait", queued: "wait", plan_pending: "wait", paused: "wait", warn: "wait", degraded: "wait",
  blocked: "risk", failed: "risk", error: "risk", rejected: "risk", detached: "risk", retired: "neutral", overdue: "risk", fail: "risk",
  backlog: "neutral", todo: "outline", cancelled: "neutral", draft: "neutral", skipped: "neutral",
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
