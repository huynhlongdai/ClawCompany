"use client";
import {useEffect} from "react";
import {EmptyState} from "../../components/ui/EmptyState";
import {Button, ButtonLink} from "../../components/ui/Button";
import {t} from "../../lib/i18n";

/* Ranh giới lỗi cho mọi trang trong shell: trang hỏng không kéo sập menu. */
export default function AppError({error, reset}: {error: Error & {digest?: string}; reset: () => void}) {
  useEffect(() => { console.warn(t("app.trang_gap_loi_khi_ve"), error?.message); }, [error]);
  return <EmptyState mood="loi" title={t("app.trang_nay_gap_loi_khi")}
    action={<div className="ui-confirm-actions"><Button variant="primary" onClick={reset}>{t("app.thu_lai")}</Button><ButtonLink href="/app/inbox">{t("app.ve_hop_viec")}</ButtonLink></div>}>
    {t("app.menu_va_cac_trang_khac")}
    {error?.digest ? t("app.ma", {p0: error.digest}) : ""}.<br/><small>{t("app.chi_tiet")} {String(error?.message || t("app.khong_ro")).slice(0, 200)}</small>
  </EmptyState>;
}
