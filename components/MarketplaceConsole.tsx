"use client";
import {useEffect, useState} from "react";
import {api, apiV8} from "../lib/api";
import {Icon} from "./Icon";

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
    catch (e: any) { setError(e?.message || "Không tải được marketplace"); }
  }
  useEffect(() => { load(); }, []);

  async function install(row: Row) {
    setBusy(row.id); setResult("");
    try {
      const out = await apiV8.companyFactoryInstall({
        organization_id: row.organization_id, template_id: row.id,
      });
      setResult(`Đã tạo job cài đặt: ${JSON.stringify(out).slice(0, 160)}`);
    } catch (e: any) {
      setResult(`Không cài được: ${String(e?.message || e).slice(0, 200)}`);
    } finally { setBusy(null); }
  }

  return <div>
    {error && <div className="v8Error" style={{marginBottom: 14}}>{error}</div>}
    {result && <div className="panel" style={{marginBottom: 14}}><small>{result}</small></div>}

    <section className="v10Grid">
      {rows.map(r => <div key={r.id} className="panel">
        <div className="companyTop">
          <div className={`iconTile ${KIND_TINT[r.template_type] || "blue"}`}>
            <Icon name={r.template_type === "company" ? "building" : "sparkle"} size={18}/>
          </div>
          <div style={{minWidth: 0, flex: 1}}>
            <b style={{display: "block", fontSize: 14}}>{r.name}</b>
            <small>{r.template_type} · v{r.version} · {r.author || "—"}</small>
          </div>
          <span className={`tag ${r.status === "published" ? "greenTag" : "orangeTag"}`}>{r.status}</span>
        </div>

        <div className="divider"/>

        <div className="companyMeta" style={{marginTop: 0}}>
          <span>{(r.installs || 0).toLocaleString("vi-VN")} lượt cài</span>
          <b>{r.price ? `$${r.price}` : "Miễn phí"}</b>
        </div>

        <div className="heroActions" style={{marginTop: 12}}>
          <button className="v8Primary" disabled={busy === r.id || r.template_type !== "company"}
                  onClick={() => install(r)}
                  title={r.template_type !== "company"
                    ? "Chỉ template loại company có luồng cài đặt thật (v8 company factory)"
                    : "Cài vào tổ chức của bạn"}>
            {busy === r.id ? "Đang cài…" : "Cài đặt"}
          </button>
          <a className="v8Ghost" href="/app/company-factory">Xem job cài đặt →</a>
        </div>
      </div>)}
      {!rows.length && <div className="v8Empty">Chưa có template nào.</div>}
    </section>

    <small style={{display: "block", marginTop: 14}}>
      Nút "Cài đặt" gọi thật <code>/api/company-factory/install</code>; template
      không phải loại <code>company</code> thì v8 chưa có luồng cài, nên nút bị khoá
      thay vì bấm vào không có gì xảy ra.
    </small>
  </div>;
}
