import "../design/brand/tokens.css";
import "./styles/fonts.css";
import "./styles/system.css";
import "./styles/ui.css";
import "./styles/pages.css";
import "./styles/legacy.css";
import type {Metadata, Viewport} from "next";
import {cookies} from "next/headers";
import {THEME_BOOT} from "../lib/theme-boot";
import {LOCALE_COOKIE, normalizeLocale} from "../lib/i18n";
import {LocaleSync} from "../components/LocaleSync";

/* UI v2: một tầng token (design/brand/tokens.css, đã chốt) + system/ui/pages/legacy.
   Font Be Vietnam Pro + JetBrains Mono tự host (app/styles/fonts.css). Script
   nhỏ trong <head> đặt data-theme TRƯỚC khi vẽ nên không nháy sáng→tối. */
export const metadata: Metadata = {
  title: {default: "ClawCompany", template: "%s · ClawCompany"},
  description: "Điều hành công ty cùng đội agent OpenClaw",
};
export const viewport: Viewport = {
  width: "device-width", initialScale: 1, viewportFit: "cover",
  themeColor: [{media: "(prefers-color-scheme: light)", color: "#FFF7F0"}, {media: "(prefers-color-scheme: dark)", color: "#12131C"}],
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  // i18n: ngôn ngữ lấy từ cookie (mặc định vi). Không có tiền tố URL.
  const locale = normalizeLocale(cookies().get(LOCALE_COOKIE)?.value);
  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{__html: THEME_BOOT}}/>
        <link rel="preload" href="/fonts/be-vietnam-pro-vietnamese-400-normal.woff2" as="font" type="font/woff2" crossOrigin="anonymous"/>
        <link rel="preload" href="/fonts/be-vietnam-pro-latin-400-normal.woff2" as="font" type="font/woff2" crossOrigin="anonymous"/>
      </head>
      <body><LocaleSync locale={locale}>{children}</LocaleSync></body>
    </html>
  );
}
