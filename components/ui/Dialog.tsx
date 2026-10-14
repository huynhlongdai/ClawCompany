"use client";
import {ReactNode, useEffect, useRef} from "react";
import {IconButton} from "./Button";
import {t} from "../../lib/i18n";

/* Hộp thoại + side-peek (Sheet). Cả hai: Esc đóng, bấm nền đóng, khoá cuộn trang,
   giữ focus bên trong (Tab vòng), trả focus về nút đã mở khi đóng. */
function useOverlay(onClose: () => void, ref: React.RefObject<HTMLElement>, lockScroll = true) {
  const closeRef = useRef(onClose); closeRef.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>("[autofocus],input:not([type=hidden]),select,textarea,button:not([disabled]),[href]");
    (window.matchMedia("(pointer:fine)").matches && first ? first : el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); return; }
      if (e.key !== "Tab" || !el) return;
      const f = Array.from(el.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex='-1'])"));
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    if (lockScroll) document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; opener?.focus?.(); };
  }, [ref, lockScroll]);
}

export function Dialog({title, onClose, children, actions, testId, as = "div", onSubmit, wide}: {
  title: ReactNode; onClose: () => void; children: ReactNode; actions?: ReactNode; testId?: string;
  as?: "div" | "form"; onSubmit?: (e: React.FormEvent) => void; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement & HTMLFormElement>(null);
  useOverlay(onClose, ref);
  const Tag = as as any;
  return <div className="ui-dialog-wrap" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <Tag ref={ref} className="ui-dialog" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}
         tabIndex={-1} data-testid={testId} onSubmit={onSubmit} style={wide ? {width: "min(720px,100%)"} : undefined}>
      <header><h2>{title}</h2><IconButton icon="x" label={t("ui.dong_esc")} onClick={onClose}/></header>
      {children}
      {actions && <div className="ui-dialog-actions">{actions}</div>}
    </Tag>
  </div>;
}

export function Sheet({label, onClose, head, children, testId}: {
  label: string; onClose: () => void; head?: ReactNode; children: ReactNode; testId?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  useOverlay(onClose, ref, false);
  return <div className="ui-sheet-wrap" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <aside ref={ref} className="ui-sheet" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} data-testid={testId}>
      <header className="ui-sheet-head">{head}<span className="ui-grow"/><IconButton icon="x" label={t("ui.dong_esc")} onClick={onClose} data-testid={testId ? testId + "-close" : undefined}/></header>
      <div className="ui-sheet-body">{children}</div>
    </aside>
  </div>;
}
