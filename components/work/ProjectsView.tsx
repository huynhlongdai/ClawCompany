"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {apiV17, apiV36} from "../../lib/api";
import {StatusPill, toneOf} from "../ui/StatusPill";
import {EmptyState, ErrorBanner, ErrorState} from "../ui/EmptyState";
import {SkeletonRows} from "../ui/Skeleton";
import {useToast} from "../ui/Toast";
import {t, lazy} from "../../lib/i18n";

/* Công việc › Dự án: tiến độ dẫn xuất từ việc, hạn chót sửa tại chỗ (projects.due_date, v36). */
const STATUS_VI: Record<string, string> = lazy(() => ({active: t("work.dang_chay"), planning: t("work.len_ke_hoach"), paused: t("work.tam_dung_2"), completed: "Xong", archived: t("work.luu_tru"), draft: t("work.nhap")}));
function daysLeft(due: string) {
  const d = Math.round((new Date(due + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / 86400000);
  return d < 0 ? {text: t("work.qua_han_ngay", {p0: -d}), late: true} : d === 0 ? {text: t("work.han_hom_nay"), late: true} : {text: t("work.con_ngay", {p0: d}), late: false};
}

export function ProjectsView() {
  const [rows, setRows] = useState<any[] | null>(null), [error, setError] = useState<unknown>(null), [saveErr, setSaveErr] = useState<unknown>(null);
  const toast = useToast();
  const load = useCallback(() => { setError(null); apiV17.projects().then(r => setRows(r || [])).catch(setError); }, []);
  useEffect(() => { load(); }, [load]);
  async function setDue(id: number, value: string | null) {
    setSaveErr(null);
    try { await apiV36.setDueDate(id, value); setRows(rs => (rs || []).map(r => r.id === id ? {...r, due_date: value} : r)); toast(value ? t("work.da_dat_han_chot") : t("work.da_bo_han_chot")); }
    catch (e) { setSaveErr(e); }
  }
  if (error) return <ErrorState error={error} onRetry={load} context={t("work.tai_du_an")}/>;
  if (!rows) return <SkeletonRows n={5}/>;
  if (!rows.length) return <EmptyState mood="chao" title={t("work.chua_co_du_an")} action={<Link className="ui-btn is-primary" href="/onboarding">{t("work.dung_cong_ty_tu_mau")}</Link>}>
    {t("work.viec_luon_nam_trong_mot")}</EmptyState>;
  return <div className="wk-projects" data-testid="wk-projects">
    {saveErr ? <ErrorBanner error={saveErr} onClose={() => setSaveErr(null)} context={t("work.luu_han_chot")}/> : null}
    <div className="ui-panel"><div className="ui-table-wrap"><table className="ui-table">
      <thead><tr><th>{t("work.du_an")}</th><th>{t("work.cong_ty")}</th><th style={{width: 180}}>{t("work.tien_do")}</th><th className="is-num">{t("work.viec_xong")}</th><th>{t("work.han_chot")}</th><th>{t("work.trang_thai")}</th></tr></thead>
      <tbody>{rows.map(p => { const left = p.due_date ? daysLeft(p.due_date) : null;
        return <tr key={p.id}>
          <td>{p.name}</td><td>{p.company_name || "—"}</td>
          <td><div style={{display: "flex", alignItems: "center", gap: 8}}><div className="ui-meter" style={{flex: 1}}><i style={{width: `${p.progress || 0}%`}}/></div>
            <span className="ui-num" style={{fontSize: 12, color: "var(--text-muted)", minWidth: 34}}>{p.progress || 0}%</span></div></td>
          <td className="is-num">{p.tasks_done}/{p.tasks_total}</td>
          <td><input type="date" value={p.due_date || ""} aria-label={t("work.han_chot_2", {p0: p.name})} onChange={e => setDue(p.id, e.target.value || null)}/>
            {left && <small style={{display: "block", marginTop: 2, color: left.late ? "var(--risk)" : undefined}}>{left.text}</small>}</td>
          <td><StatusPill tone={toneOf(p.status)}>{STATUS_VI[p.status] || p.status}</StatusPill></td>
        </tr>; })}</tbody>
    </table></div></div>
  </div>;
}
