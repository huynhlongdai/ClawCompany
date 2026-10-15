import {t, type Key} from "@/lib/i18n";

/* Nhãn loại phê duyệt và hạn duyệt theo ngôn ngữ đang dùng, dựng từ dữ liệu thô
   (kind, seconds_left, escalate_to, escalated_at) thay vì kind_vi/deadline_vi của backend. */
const KINDS = ["stage", "plan", "budget", "gateway", "lesson", "authority"];

export function kindLabel(kind?: string | null): string {
  return t(`inbox.kind_${KINDS.includes(kind || "") ? kind : "other"}` as Key);
}

type DL = {seconds_left?: number | null; escalate_to?: string | null; escalated_at?: string | null};
export function deadlineText(a: DL): string {
  const s = a.seconds_left;
  if (s == null) return "";
  if (s <= 0) return a.escalate_to ? t("inbox.dl_overdue_esc", {p0: a.escalate_to}) : t("inbox.dl_overdue_none");
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  const left = [h ? t("inbox.dl_h", {p0: h}) : "", t("inbox.dl_m", {p0: m})].filter(Boolean).join(" ");
  return t("inbox.dl_left", {p0: left}) + (a.escalated_at ? t("inbox.dl_escalated") : "");
}
