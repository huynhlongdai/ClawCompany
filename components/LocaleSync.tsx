"use client";
import {useEffect} from "react";
import {Locale, Messages, setLocale, setMessages} from "../lib/i18n";

/* Đặt locale cho lượt render (SSR và client) từ cookie mà app/layout.tsx đọc được.
   Gọi setLocale ngay trong render để con bên dưới dùng t() đúng ngôn ngữ. */
export function LocaleSync({locale, messages, children}: {locale: Locale; messages: Messages; children: React.ReactNode}) {
  setLocale(locale); setMessages(messages);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  return <>{children}</>;
}
