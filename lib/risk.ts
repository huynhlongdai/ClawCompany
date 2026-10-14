import {t, type Key} from "@/lib/i18n";

/** Nhãn mức rủi ro theo ngôn ngữ đang dùng (không dựa vào risk_vi của backend). */
export function riskLabel(risk?: string | null): string {
  const r = risk === "low" || risk === "high" || risk === "critical" ? risk : "medium";
  return t(`inbox.risk_${r}` as Key);
}
