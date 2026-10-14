/* Tuỳ chọn phía trình duyệt (localStorage), có đăng ký lắng nghe để mọi nơi
   dùng cùng một giá trị: cờ Phòng thí nghiệm, giao diện sáng/tối, công ty đang
   xem. Đọc bằng useSyncExternalStore nên không lệch giữa server và client
   (server luôn trả giá trị mặc định). */
import {useSyncExternalStore} from "react";

type Key = "cc_lab" | "cc_theme" | "cc_company";
const listeners = new Set<() => void>();
const emit = () => listeners.forEach(fn => fn());
function subscribe(fn: () => void) {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => { if (e.key?.startsWith("cc_")) fn(); };
  window.addEventListener("storage", onStorage);
  return () => { listeners.delete(fn); window.removeEventListener("storage", onStorage); };
}
function read(key: Key): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
export function writePref(key: Key, value: string | null) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* chế độ riêng tư */ }
  emit();
}
function usePref(key: Key, fallback: string): string {
  return useSyncExternalStore(subscribe, () => read(key) ?? fallback, () => fallback);
}

/* Phòng thí nghiệm: mặc định TẮT (plan §2), bản cài có thể bật sẵn bằng NEXT_PUBLIC_LAB=on. */
const LAB_DEFAULT = process.env.NEXT_PUBLIC_LAB === "on" ? "on" : "off";
export function useLab(): [boolean, (on: boolean) => void] {
  const v = usePref("cc_lab", LAB_DEFAULT);
  return [v === "on", (on: boolean) => writePref("cc_lab", on ? "on" : "off")];
}

/* Giao diện: "system" | "light" | "dark". Script trong <head> áp trước khi vẽ (không nháy). */
export type ThemePref = "system" | "light" | "dark";
export function useThemePref(): [ThemePref, (t: ThemePref) => void] {
  const v = usePref("cc_theme", "system") as ThemePref;
  return [v, (t: ThemePref) => { writePref("cc_theme", t === "system" ? null : t); applyTheme(t); }];
}
export function applyTheme(t: ThemePref) {
  const dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#12131C" : "#FFF7F0");
}

/* Công ty đang xem (một tổ chức có nhiều công ty). Trang nào lọc được theo công ty thì đọc giá trị này. */
export function useCompanyId(): [number | null, (id: number | null) => void] {
  const v = usePref("cc_company", "");
  return [v ? Number(v) : null, (id: number | null) => writePref("cc_company", id ? String(id) : null)];
}
