"use client";
import Link from "next/link";
import {useEffect, useState} from "react";
import {LanguageSwitcher} from "../LanguageSwitcher";
import {Icon} from "../Icon";
import {Panel} from "../ui/Panel";
import {Segmented} from "../ui/Tabs";
import {StatusPill} from "../ui/StatusPill";
import {ButtonLink} from "../ui/Button";
import {useCounts} from "../shell/Shell";
import {useOrg} from "../../lib/counts";
import {apiV19} from "../../lib/api";
import {ThemePref, useCompanyId, useLab, useThemePref} from "../../lib/prefs";
import {LAB_PAGES} from "../../lib/nav";
import {t, lazy} from "../../lib/i18n";

const SHORTCUTS: [string, string][] = lazy(() => ([["Ctrl K / ⌘K", t("settings.tim_va_di_toi_moi")], ["C", t("settings.tao_viec_trong_cong_viec")], ["/", t("settings.tim_viec")],
  ["J · K", t("settings.chon_viec_tren_duoi")], ["Enter", t("settings.mo_side_peek")], ["Esc", t("settings.dong_side_peek_hop_thoai")]]));

export function SettingsHome() {
  useCounts();
  const org = useOrg();
  const [theme, setTheme] = useThemePref();
  const [lab] = useLab();
  const [companyId, setCompanyId] = useCompanyId();
  const [health, setHealth] = useState<any>(null), [hErr, setHErr] = useState(false);
  useEffect(() => { apiV19.health().then(setHealth).catch(() => setHErr(true)); }, []);
  const status = health?.health?.status;
  return <div className="ui-grid is-2">
    <Panel title={t("settings.ket_noi_openclaw")} desc={t("settings.gateway_chay_agent_cua_cong")} actions={<ButtonLink href="/app/openclaw" size="sm">{t("settings.mo_kiem_tra")}</ButtonLink>}>
      <div className="set-line">
        {hErr ? <StatusPill tone="risk">{t("settings.khong_doc_duoc_trang_thai")}</StatusPill>
          : !health ? <StatusPill tone="neutral">{t("settings.dang_kiem_tra")}</StatusPill>
          : <StatusPill tone={status === "healthy" ? "ok" : "wait"}>{status === "healthy" ? t("settings.dang_ket_noi") : t("settings.chua_san_sang", {p0: status || "không rõ"})}</StatusPill>}
        <span className="ui-row-meta">{health?.runtime?.mode ? t("settings.che_do", {p0: health.runtime.mode}) : t("settings.chay_kiem_tra_lai_o")}</span>
      </div>
    </Panel>
    <Panel title={t("settings.giao_dien")} desc={t("settings.luu_tren_trinh_duyet_nay")}>
      <Segmented<ThemePref> label={t("settings.giao_dien")} value={theme} onChange={setTheme}
        options={[{value: "light", label: t("settings.sang")}, {value: "dark", label: t("settings.toi")}, {value: "system", label: t("settings.theo_may")}]}/>
    </Panel>
    <Panel title={t("shell.ngon_ngu")} desc={t("settings.ngon_ngu_desc")} testId="settings-language">
      <LanguageSwitcher/>
    </Panel>
    <Panel title={t("settings.cong_ty")} desc={org.name ? t("settings.to_chuc", {p0: org.name}) : t("settings.dang_tai")} flush actions={<ButtonLink href="/onboarding" size="sm" icon="plus">{t("settings.tao_cong_ty")}</ButtonLink>}>
      <div className="ui-list">
        {org.companies.map(c => <button key={c.id} className="ui-row" onClick={() => setCompanyId(c.id)} aria-pressed={c.id === (companyId ?? org.companies[0]?.id)}>
          <Icon name="building" size={16}/><span className="ui-row-main"><span className="ui-row-title">{c.name}</span><span className="ui-row-meta">{c.industry || "—"}</span></span>
          {c.id === (companyId ?? org.companies[0]?.id) && <StatusPill tone="ok">{t("settings.dang_xem")}</StatusPill>}
        </button>)}
        {!org.companies.length && <p className="ui-row ui-row-meta">{t("settings.chua_co_cong_ty_nao")}</p>}
      </div>
    </Panel>
    <Panel title={t("settings.phong_thi_nghiem")} desc={t("settings.trang_it_dung_giao_phan", {p0: LAB_PAGES.length})}
      actions={<ButtonLink href="/app/settings/lab" size="sm">{lab ? t("settings.dang_bat") : t("settings.dang_tat")} {t("settings.quan_ly")}</ButtonLink>}>
      <p className="ui-row-meta" style={{whiteSpace: "normal"}}>{t("settings.an_khoi_menu_va_tim")}</p>
    </Panel>
    <Panel title={t("settings.phim_tat")} flush>
      <div className="ui-list">{SHORTCUTS.map(([k, d]) => <div key={k} className="ui-row"><kbd>{k}</kbd><span className="ui-row-meta" style={{whiteSpace: "normal"}}>{d}</span></div>)}</div>
    </Panel>
    <Panel title={t("settings.ky_nang_bi_mat_thanh")} flush>
      <div className="ui-list">
        <Link className="ui-row" href="/app/agent-tools"><Icon name="shield" size={16}/><span className="ui-row-main"><span className="ui-row-title">{t("settings.ky_nang_cong_cu")}</span><span className="ui-row-meta">{t("settings.cong_cu_agent_duoc_goi")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/secrets"><Icon name="key" size={16}/><span className="ui-row-main"><span className="ui-row-title">{t("settings.bi_mat")}</span><span className="ui-row-meta">{t("settings.tham_chieu_khoa_cap_quyen")}</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/team?tab=people&from=settings"><Icon name="users" size={16}/><span className="ui-row-main"><span className="ui-row-title">{t("settings.thanh_vien")}</span><span className="ui-row-meta">{t("settings.moi_nguoi_doi_vai_thu")}</span></span><Icon name="chevron-right" size={14}/></Link>
      </div>
    </Panel>
  </div>;
}
