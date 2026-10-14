"use client";
import Link from "next/link";
import {Icon} from "../Icon";
import {Panel} from "../ui/Panel";
import {useEffect, useState} from "react";
import {ErrorBanner, Notice} from "../ui/EmptyState";
import {StatusPill} from "../ui/StatusPill";
import {SkeletonRows} from "../ui/Skeleton";
import {api} from "../../lib/api";
import {LAB_PAGES} from "../../lib/nav";
import {useLab} from "../../lib/prefs";
import {t} from "../../lib/i18n";

/* Cờ Phòng thí nghiệm (plan-v2 §2): ẩn 27 trang ít dùng khỏi menu và ⌘K. Route vẫn chạy.
   Cờ nằm ở trình duyệt (localStorage) — mặc định tắt, bản cài đặt có thể bật sẵn bằng NEXT_PUBLIC_LAB=on. */
export function LabSettings() {
  const [lab, setLab] = useLab();
  const areas = Array.from(new Set(LAB_PAGES.map(p => p.area)));
  return <div className="ui-grid" style={{gap: 20}}>
    <Panel title={t("settings.phong_thi_nghiem")} desc={t("settings.trang_cua_cac_module_chua")}>
      <label className="set-switch" data-testid="lab-toggle">
        <input type="checkbox" role="switch" checked={lab} onChange={e => setLab(e.target.checked)}/>
        <span><b>{lab ? t("settings.dang_bat") : t("settings.dang_tat")}</b><small>{lab ? t("settings.trang_hien_trong_k_va", {p0: LAB_PAGES.length}) : t("settings.trang_dang_an_khoi_tim", {p0: LAB_PAGES.length})}</small></span>
      </label>
    </Panel>
    <LabJobsPanel/>
    {lab && areas.map(a => <Panel key={a} title={a} flush>
      <div className="ui-list">{LAB_PAGES.filter(p => p.area === a).map(p => <Link key={p.href} href={p.href} className="ui-row">
        <Icon name={p.icon} size={16}/><span className="ui-row-main"><span className="ui-row-title">{p.label}</span><span className="ui-row-meta">{p.desc}</span></span>
        <Icon name="chevron-right" size={14}/></Link>)}</div>
    </Panel>)}
  </div>;
}

/* Cờ backend LAB_JOBS_ENABLED: đọc từ /api/health/lab — trình duyệt không bật/tắt được, phải đổi env của api + worker. */
function LabJobsPanel() {
  const [st, setSt] = useState<{lab_jobs_enabled: boolean; env: string; jobs: string[]} | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const load = () => { setErr(null); api.labStatus().then(setSt).catch(setErr); };
  useEffect(load, []);
  const on = !!st?.lab_jobs_enabled;
  return <Panel title={t("settings.job_nen_cua_phong_thi")} testId="lab-jobs"
    desc={t("settings.co_may_chu_khac_voi")}
    actions={st ? <StatusPill tone={on ? "wait" : "ok"}>{on ? t("settings.dang_chay") : t("settings.da_tat")}</StatusPill> : undefined}>
    {err ? <ErrorBanner error={err} onRetry={load} context={t("settings.doc_trang_thai_job_nen")}/> : !st ? <SkeletonRows n={2} h={28}/> : <>
      {on
        ? <Notice tone="wait"><b>{st.env}=true.</b> {t("settings.k6_job_dang_duoc_lap")} <code>v15.control_plane_tick</code> {t("settings.co_the_tao_phe_duyet")}</Notice>
        : <Notice tone="ok"><b>{st.env}{t("settings.false_mac_dinh")}</b> {t("settings.k6_job_khong_duoc_lap")} <code>{st.env}=true</code> {t("settings.cho_api_va_worker_roi")}</Notice>}
      <div className="ui-table-wrap" style={{marginTop: 12}}><table className="ui-table">
        <thead><tr><th>Job</th><th>{t("settings.trang_thai")}</th></tr></thead>
        <tbody>{st.jobs.map(j => <tr key={j}><td><code>{j}</code></td><td><StatusPill tone={on ? "wait" : "neutral"}>{on ? t("settings.lap_lich") : t("settings.tat")}</StatusPill></td></tr>)}</tbody>
      </table></div>
    </>}
  </Panel>;
}
