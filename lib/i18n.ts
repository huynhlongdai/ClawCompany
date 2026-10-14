/* i18n tối giản (không thư viện): từ điển JSON có kiểu + hàm t().

   - messages/vi.json là nguồn (mặc định, fallback); messages/en.json phải có ĐÚNG
     các khoá đó: thiếu khoá → `npx tsc` lỗi ở dòng `const EN: Messages = en`.
     Thừa khoá → tools/i18n_check.mjs báo (tsc không bắt được thừa).
   - Locale nằm ở cookie `cc_locale` (+ hồ sơ người dùng ở backend). Không có
     tiền tố URL. Server đọc cookie trong app/layout.tsx → <html lang> và
     <LocaleSync> đặt locale cho lượt render; client đọc lại từ <html lang>.
   - t() là hàm thường (không phải hook) nên dùng được ở mọi chỗ trong lúc render.
     Đổi ngôn ngữ = ghi cookie + tải lại trang, nên không cần context để re-render.
   - Hằng ở cấp module (bảng nhãn, menu) bọc bằng lazy(() => …): đọc lại theo locale
     hiện tại mỗi lần truy cập — không bị "đóng băng" theo locale lúc import. */
import vi from "../messages/vi.json";
import en from "../messages/en.json";

export type Locale = "vi" | "en";
export const LOCALES: Locale[] = ["vi", "en"];
export type Messages = typeof vi;
const EN: Messages = en;
type NS = keyof Messages;
export type Key = {[N in NS]: `${N & string}.${keyof Messages[N] & string}`}[NS];
export type Vars = Record<string, string | number | null | undefined>;

const DICTS: Record<Locale, Messages> = {vi, en: EN};
export const LOCALE_COOKIE = "cc_locale";

export function normalizeLocale(x: unknown): Locale { return x === "en" ? "en" : "vi"; }

let current: Locale = typeof document !== "undefined" ? normalizeLocale(document.documentElement.lang) : "vi";
export function setLocale(l: Locale) { current = l; }
export function getLocale(): Locale { return current; }
export const intlLocale = (l: Locale = current) => (l === "en" ? "en-US" : "vi-VN");

export function t(key: Key, vars?: Vars): string {
  const i = key.indexOf(".");
  const ns = key.slice(0, i), k = key.slice(i + 1);
  const s: string = (DICTS[current] as any)[ns]?.[k] ?? (vi as any)[ns]?.[k] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (m, n) => (vars[n] != null ? String(vars[n]) : m)) : s;
}

/** Hằng cấp module phụ thuộc ngôn ngữ: object/array dựng lại theo locale khi được đọc. */
export function lazy<T extends object>(factory: () => T): T {
  const cache: Partial<Record<Locale, T>> = {};
  const get = (): any => (cache[current] ??= factory());
  const target: any = Array.isArray(factory()) ? [] : {}; // Array.isArray(proxy) theo target
  return new Proxy(target, {
    get: (_, p) => { const real = get(), v = real[p]; return typeof v === "function" ? v.bind(real) : v; },
    has: (_, p) => p in get(),
    ownKeys: () => Reflect.ownKeys(get()),
    getOwnPropertyDescriptor: (_, p) => {
      const real = get(), d = Reflect.getOwnPropertyDescriptor(real, p);
      if (!d) return d;
      if (Array.isArray(real) && p === "length") return {value: real.length, writable: true, enumerable: false, configurable: false};
      return {...d, configurable: true};
    },
    getPrototypeOf: () => Object.getPrototypeOf(get()),
  }) as T;
}

/* ---- Định dạng theo locale (Intl) ---- */
const toDate = (s: string | number | Date) => {
  if (s instanceof Date || typeof s === "number") return new Date(s);
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z"); // backend trả UTC không có hậu tố
};
export function fmtDate(s?: string | number | Date | null, opts: Intl.DateTimeFormatOptions = {day: "2-digit", month: "2-digit", year: "numeric"}) {
  if (s == null || s === "") return "—";
  const d = toDate(s); return isNaN(d.getTime()) ? String(s) : d.toLocaleDateString(intlLocale(), opts);
}
export function fmtDateTime(s?: string | number | Date | null, opts: Intl.DateTimeFormatOptions = {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"}) {
  if (s == null || s === "") return "—";
  const d = toDate(s); return isNaN(d.getTime()) ? String(s) : d.toLocaleString(intlLocale(), opts);
}
export function fmtTime(s?: string | number | Date | null) {
  if (s == null || s === "") return "—";
  const d = toDate(s); return isNaN(d.getTime()) ? String(s) : d.toLocaleTimeString(intlLocale(), {hour: "2-digit", minute: "2-digit"});
}
export function fmtNum(n?: number | null, opts?: Intl.NumberFormatOptions) {
  return n == null || isNaN(Number(n)) ? "—" : Number(n).toLocaleString(intlLocale(), opts);
}
/** Chi phí model tính bằng USD ở mọi locale (đơn vị của nhà cung cấp model); chỉ cách viết số đổi theo locale. */
export function fmtUsd(n?: number | null, digits = 2) {
  return n == null || isNaN(Number(n)) ? "—" : Number(n).toLocaleString(intlLocale(), {style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 2)});
}
export function fmtRelative(s?: string | number | Date | null) {
  if (s == null || s === "") return "—";
  const d = toDate(s); if (isNaN(d.getTime())) return String(s);
  const sec = Math.round((d.getTime() - Date.now()) / 1000), a = Math.abs(sec);
  const rtf = new Intl.RelativeTimeFormat(intlLocale(), {numeric: "auto"});
  if (a < 60) return rtf.format(sec, "second");
  if (a < 3600) return rtf.format(Math.round(sec / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(sec / 3600), "hour");
  return rtf.format(Math.round(sec / 86400), "day");
}

/** Đổi ngôn ngữ: cookie (server đọc) + localStorage, rồi tải lại để mọi chuỗi + <html lang> đổi theo. */
export function writeLocaleCookie(l: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${l}; path=/; max-age=31536000; samesite=lax`;
  try { localStorage.setItem(LOCALE_COOKIE, l); } catch { /* chế độ riêng tư */ }
}
export function readLocaleCookie(): Locale | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|; )cc_locale=(vi|en)/);
  return m ? (m[1] as Locale) : null;
}
