import "server-only";
import type {Locale, Messages} from "./i18n";

/* Đọc đúng một catalog theo locale, chỉ ở server. vi là mặc định và fallback. */
export async function loadMessages(locale: Locale): Promise<Messages> {
  return locale === "en" ? (await import("../messages/en.json")).default as Messages : (await import("../messages/vi.json")).default;
}
