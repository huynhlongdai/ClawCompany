import {EmptyState} from "../components/ui/EmptyState";
import {ButtonLink} from "../components/ui/Button";
import {cookies} from "next/headers";
import {LOCALE_COOKIE, normalizeLocale, setLocale, t} from "../lib/i18n";

export default function NotFound() {
  setLocale(normalizeLocale(cookies().get(LOCALE_COOKIE)?.value)); // server component: lớp RSC có biến locale riêng
  return <EmptyState mood="ngu" title={t("app.khong_co_trang_nay")} action={<ButtonLink href="/app/os" variant="primary">{t("app.ve_tong_quan")}</ButtonLink>}>
    {t("app.duong_dan_co_the_da")}
  </EmptyState>;
}
