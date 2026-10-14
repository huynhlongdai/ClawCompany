import {AuthGate} from "../../components/AuthGate";
import {Onboarding} from "../../components/onboarding/Onboarding";
import {ToastProvider} from "../../components/ui/Toast";

import {cookies} from "next/headers";
import {LOCALE_COOKIE, normalizeLocale} from "../../lib/i18n";
import {loadMessages} from "../../lib/messages.server";

// Tiêu đề tab theo ngôn ngữ (server đọc cookie) — dùng lại nhãn “Dựng công ty” trong nav.
export async function generateMetadata() {
  const m = await loadMessages(normalizeLocale(cookies().get(LOCALE_COOKIE)?.value));
  return {title: m.nav.dung_cong_ty};
}

/* Onboarding 4 bước (plan §5) — toàn màn, không có menu để người mới không bị 8 mục làm rối. */
export default function Page() {
  return <AuthGate><ToastProvider><Onboarding/></ToastProvider></AuthGate>;
}
