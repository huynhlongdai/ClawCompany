"use client";
import {createContext, ReactNode, useCallback, useContext, useMemo, useState} from "react";
import {Icon} from "../Icon";
import {t as tr} from "../../lib/i18n";

/* Thông báo ngắn sau một thao tác. Một vùng aria-live cho cả app (gắn trong Shell). */
type T = {id: number; text: string; tone: "info" | "error"};
const Ctx = createContext<(text: string, tone?: "info" | "error") => void>(() => {});
let seq = 0;

export function ToastProvider({children}: {children: ReactNode}) {
  const [items, setItems] = useState<T[]>([]);
  const drop = useCallback((id: number) => setItems(xs => xs.filter(x => x.id !== id)), []);
  const push = useCallback((text: string, tone: "info" | "error" = "info") => {
    const id = ++seq;
    setItems(xs => [...xs.slice(-2), {id, text, tone}]);
    setTimeout(() => drop(id), tone === "error" ? 8000 : 4500);
  }, [drop]);
  const value = useMemo(() => push, [push]);
  return <Ctx.Provider value={value}>
    {children}
    <div className="ui-toasts" aria-live="polite" aria-atomic="false">
      {items.map(t => <div key={t.id} className={"ui-toast" + (t.tone === "error" ? " is-error" : "")} role={t.tone === "error" ? "alert" : "status"}>
        <Icon name={t.tone === "error" ? "alert" : "check"} size={16}/><span style={{flex: 1}}>{t.text}</span>
        <button type="button" onClick={() => drop(t.id)} aria-label={tr("ui.dong_thong_bao")}><Icon name="x" size={14}/></button>
      </div>)}
    </div>
  </Ctx.Provider>;
}
export const useToast = () => useContext(Ctx);
