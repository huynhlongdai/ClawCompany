"use client";
import {useEffect, useState} from "react";
import {api, apiV8} from "../lib/api";
import {Icon} from "./Icon";
import {intlLocale, t} from "../lib/i18n";
import {ErrorBanner} from "./ui/EmptyState";

/* Marketplace — có trong mẫu, app chưa có route.
   Dữ liệu thật: /api/marketplace (marketplace_templates: tên, loại, tác giả,
   phiên bản, giá, số lượt cài, trạng thái).

   Nút "Cài đặt" gọi /api/company-factory/install cho template loại company —
   đúng luồng mà v8 đã có, không phải nút giả. */

type Row = Record<string, any>;

const KIND_TINT: Record<string, string> = {
  company: "violet", employee: "blue", workflow: "green", department: "amber",
};

export function MarketplaceConsole() {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [result, setResult] = useState("");

  async function load() {
    try { setRows((await api.marketplace() as Row[]) || []); }
    catch (e: any) { setError(e?.message || t("market.load_failed")); }
  }
  useEffect(() => { load(); }, []);

  async function install(row: Row) {
    setBusy(row.id); setResult("");
    try {
      const out = await apiV8.companyFactoryInstall({
        organization_id: row.organization_id, template_id: row.id,
      });
      setResult(t("market.job_created", {p0: JSON.stringify(out).slice(0, 160)}));
    } catch (e: any) {
      setResult(t("market.install_failed", {p0: String(e?.message || e).slice(0, 200)}));
    } finally { setBusy(null); }
  }

  return <div>
    {error && <ErrorBanner error={error}/>}
    {result && <div className="ui-panel" style={{marginBottom: 14}}><small>{result}</small></div>}

    <section className="ui-grid is-2">
      {rows.map(r => <div key={r.id} className="ui-panel">
        <div className="companyTop">
          <div className={`lab-icon ${KIND_TINT[r.template_type] || "blue"}`}>
            <Icon name={r.template_type === "company" ? "building" : "sparkle"} size={18}/>
          </div>
          <div style={{minWidth: 0, flex: 1}}>
            <b style={{display: "block", fontSize: 14}}>{r.name}</b>
            <small>{r.template_type} · v{r.version} · {r.author || "—"}</small>
          </div>
          <span className={`ui-pill ${r.status === "published" ? "is-ok" : "is-wait"}`}>{r.status}</span>
        </div>

        <div className="lab-divider"/>

        <div className="companyMeta" style={{marginTop: 0}}>
          <span>{t("market.installs", {p0: (r.installs || 0).toLocaleString(intlLocale())})}</span>
          {" · "}
          <b>{r.price ? `$${r.price}` : t("market.free")}</b>
        </div>

        <div className="ui-toolbar" style={{marginTop: 12}}>
          <button className="ui-btn is-primary" disabled={busy === r.id || r.template_type !== "company"}
                  onClick={() => install(r)}
                  title={r.template_type !== "company"
                    ? t("market.only_company")
                    : t("market.install_into_org")}>
            {busy === r.id ? t("market.installing") : t("market.install")}
          </button>
          <a className="ui-btn" href="/app/company-factory">{t("market.view_jobs")}</a>
        </div>
      </div>)}
      {!rows.length && <div className="ui-empty-line">{t("market.empty")}</div>}
    </section>

    <small style={{display: "block", marginTop: 14}}>
      {t("market.footnote")}
    </small>
  </div>;
}
