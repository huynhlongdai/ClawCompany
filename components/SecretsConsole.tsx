"use client";
import {useCallback, useEffect, useState} from "react";
import {apiV12} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill} from "./ui/StatusPill";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {useToast} from "./ui/Toast";
import {t, lazy} from "../lib/i18n";

/* Cài đặt › Bí mật (v12): ClawCompany chỉ lưu THAM CHIẾU tới bí mật (env:, vault:…) và
   quyền dùng gắn với danh tính. Giá trị chỉ được giải lúc chạy và gắn vào sandbox
   dưới dạng tệp tạm — không vào DB, không vào prompt. Form không có ô nhập giá trị. */
type Row = Record<string, any>;
const CLASS_VI: Record<string, string> = lazy(() => ({restricted: t("secrets.han_che"), confidential: t("secrets.mat"), internal: t("secrets.noi_bo"), public: t("secrets.cong_khai")}));

export function SecretsConsole() {
  const toast = useToast();
  const [items, setItems] = useState<Row[] | null>(null), [grants, setGrants] = useState<Row[]>([]), [err, setErr] = useState<unknown>(null);
  const [name, setName] = useState(""), [ref, setRef] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [s, g] = await Promise.allSettled([apiV12.secrets(), apiV12.secretGrants()]);
    if (s.status === "fulfilled") setItems((s.value as Row[]) || []); else { setErr(s.reason); setItems([]); }
    if (g.status === "fulfilled") setGrants((g.value as Row[]) || []);
  }, []);
  useEffect(() => { load(); }, [load]);
  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await apiV12.createSecret({organization_id: activeOrganizationId(), name, provider: ref.split(":")[0] || "env", external_ref: ref, classification: "restricted"});
      toast(t("secrets.da_dang_ky_tham_chieu", {p0: name})); setName(""); setRef(""); await load(); }
    catch (e2) { setErr(e2); } finally { setBusy(false); }
  }
  return <div className="ui-grid" style={{gap: 16}}>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} context={t("secrets.bi_mat")}/> : null}
    <div className="ui-grid is-2">
      <Panel title={t("secrets.dang_ky_tham_chieu_bi")} desc={t("secrets.khong_co_o_nhap_gia")}>
        <form className="ui-form" onSubmit={create}>
          <FormRow>
            <Field label={t("secrets.ten")}><input value={name} onChange={e => setName(e.target.value)} placeholder={t("secrets.vd_token_trien_khai")} autoComplete="off"/></Field>
            <Field label={t("secrets.tham_chieu")} hint={t("secrets.dang_nguon_ten_vd_env")}><input value={ref} onChange={e => setRef(e.target.value)} placeholder="env:DEPLOY_TOKEN…" spellCheck={false} autoComplete="off"/></Field>
          </FormRow>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !ref.includes(":")}>{t("secrets.dang_ky")}</Button>
        </form>
      </Panel>
      <Panel title={t("secrets.nguyen_tac")}>
        <dl className="ui-kv">
          <dt>{t("secrets.luu_gia_tri_trong_db")}</dt><dd>{t("secrets.khong_bao_gio")}</dd>
          <dt>{t("secrets.dua_vao_prompt_agent")}</dt><dd>{t("secrets.khong_bao_gio")}</dd>
          <dt>{t("secrets.luc_chay")}</dt><dd>{t("secrets.gan_vao_sandbox_duoi_dang")} <code translate="no">/run/secrets/*</code></dd>
          <dt>{t("secrets.ai_duoc_dung")}</dt><dd>{t("secrets.chi_danh_tinh_co_quyen")}</dd>
        </dl>
      </Panel>
    </div>
    <Panel title={t("secrets.tham_chieu_da_dang_ky")} desc={t("secrets.chi_thay_thong_tin_mo")} flush>
      {items && items.length === 0 ? <EmptyState compact mood="ngu" title={t("secrets.chua_co_bi_mat_nao")}>{t("secrets.dang_ky_tham_chieu_dau")}</EmptyState>
        : <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>{t("secrets.ten")}</th><th>{t("secrets.nguon")}</th><th>{t("secrets.tham_chieu")}</th><th>{t("secrets.muc")}</th></tr></thead>
          <tbody>{(items || []).map(x => <tr key={x.id}><td>{x.name}</td><td>{x.provider}</td><td><code translate="no">{x.external_ref}</code></td>
            <td><StatusPill tone="wait">{CLASS_VI[x.classification] || x.classification}</StatusPill></td></tr>)}</tbody></table></div>}
    </Panel>
    <Panel title={t("secrets.quyen_dung_dang_co")} desc={t("secrets.gan_voi_nguoi_agent_ho")} flush>
      {grants.length === 0 ? <p className="ui-empty-line" style={{padding: "12px 16px"}}>{t("secrets.chua_cap_quyen_nao")}</p>
        : <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>{t("secrets.quyen")}</th><th>{t("secrets.bi_mat")}</th><th>{t("secrets.nguoi")}</th><th>Agent</th><th>Sandbox</th><th>{t("secrets.trang_thai")}</th></tr></thead>
          <tbody>{grants.map(x => <tr key={x.id}><td>#{x.id}</td><td>#{x.secret_reference_id}</td><td>{x.member_id ? `#${x.member_id}` : "—"}</td><td>{x.agent_id ? `#${x.agent_id}` : "—"}</td>
            <td>{x.sandbox_profile_id ? `#${x.sandbox_profile_id}` : "—"}</td><td><StatusPill tone={x.is_active ? "ok" : "neutral"}>{x.is_active ? t("secrets.dang_hieu_luc") : t("secrets.da_tat")}</StatusPill></td></tr>)}</tbody></table></div>}
    </Panel>
  </div>;
}
