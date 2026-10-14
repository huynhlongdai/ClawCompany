import {EmptyState} from "../components/ui/EmptyState";
import {ButtonLink} from "../components/ui/Button";
import {cookies} from "next/headers";
import {LOCALE_COOKIE, normalizeLocale, setLocale, setMessages, t} from "../lib/i18n";
import {loadMessages} from "../lib/messages.server";

export default async function NotFound() {
  const locale = normalizeLocale(cookies().get(LOCALE_COOKIE)?.value);
  setLocale(locale); setMessages(await loadMessages(locale)); // server component: lớp RSC có biến riêng
  return <EmptyState mood="ngu" title={t("app.khong_co_trang_nay")} action={<ButtonLink href="/app/os" variant="primary">{t("app.ve_tong_quan")}</ButtonLink>}>
    {t("app.duong_dan_co_the_da")}
  </EmptyState>;
}
