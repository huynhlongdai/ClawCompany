"use client";
import {useEffect} from "react";
import {api} from "../lib/api";
import {getLocale, Locale, readLocaleCookie, t, writeLocaleCookie} from "../lib/i18n";

/* Đổi ngôn ngữ: cookie (server đọc để vẽ đúng ngôn ngữ ngay từ HTML) + hồ sơ người dùng
   (đi theo tài khoản) rồi tải lại trang — mọi chuỗi, <html lang> và định dạng ngày/số đổi theo. */
export async function changeLocale(l: Locale, opts: {saveProfile?: boolean} = {saveProfile: true}) {
  writeLocaleCookie(l);
  if (opts.saveProfile) await api.updateMe({locale: l}).catch(() => {});
  location.reload();
}

const OPTIONS: [Locale, string][] = [["vi", "Tiếng Việt"], ["en", "English"]];

export function LanguageSwitcher({compact, saveProfile = true}: {compact?: boolean; saveProfile?: boolean}) {
  const cur = getLocale();
  return <div className="ui-seg" role="radiogroup" aria-label={t("shell.ngon_ngu")} data-testid="lang-switch">
    {OPTIONS.map(([k, label]) => <button key={k} type="button" role="radio" aria-checked={cur === k} lang={k}
      onClick={() => cur !== k && changeLocale(k, {saveProfile})} data-testid={`lang-${k}`}>{compact ? k.toUpperCase() : label}</button>)}
  </div>;
}

/** Máy mới chưa có cookie: lấy ngôn ngữ đã lưu trong hồ sơ (một lần mỗi phiên tab, tránh vòng tải lại). */
export function useProfileLocale(me: {locale?: string} | null) {
  useEffect(() => {
    if (!me?.locale || (me.locale !== "vi" && me.locale !== "en")) return;
    if (readLocaleCookie() || me.locale === getLocale()) return;
    if (sessionStorage.getItem("cc_locale_synced")) return;
    sessionStorage.setItem("cc_locale_synced", "1");
    changeLocale(me.locale as Locale, {saveProfile: false});
  }, [me]);
}
