"use client";
// M2 — nhận lời mời: xem ai mời, vào đâu, vai gì; đặt mật khẩu (hoặc nhập mật
// khẩu tài khoản sẵn có) rồi vào thẳng trang Đội ngũ với đúng quyền.
import {useEffect, useState} from "react";
import {useParams, useRouter} from "next/navigation";
import {apiTeam} from "../../../lib/api";
import {LogoLockup} from "../../../components/Logo";
import {BeCang} from "../../../components/BeCang";
import {Field} from "../../../components/ui/Field";
import {Button} from "../../../components/ui/Button";
import {explain} from "../../../lib/errors";
import {t} from "../../../lib/i18n";

export default function InvitePage() {
  const {token} = useParams<{token: string}>();
  const router = useRouter();
  const [inv, setInv] = useState<any>(null), [error, setError] = useState<unknown>(null), [formErr, setFormErr] = useState("");
  const [name, setName] = useState(""), [pw, setPw] = useState(""), [pw2, setPw2] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    apiTeam.lookupInvite(token).then(x => { setInv(x); setName(x.display_name || ""); }).catch(e => setError(e));
  }, [token]);
  async function accept() {
    setError(null); setFormErr("");
    if (!inv.account_exists && pw.length < 8) { setFormErr(t("invite.mat_khau_can_it_nhat")); return; }
    if (!inv.account_exists && pw !== pw2) { setFormErr(t("invite.hai_lan_nhap_mat_khau")); return; }
    setBusy(true);
    try {
      const r = await apiTeam.acceptInvite(token, pw, name);
      localStorage.setItem("clawcompany_token", r.access_token);
      router.replace("/app/team");
    } catch (e: any) { setError(e); } finally { setBusy(false); }
  }
  const x = error ? explain(error, t("invite.nhan_loi_moi")) : null;
  return <div className="auth">
    <form className="auth-card" data-testid="invite-card" onSubmit={e => { e.preventDefault(); accept(); }} noValidate>
      <LogoLockup/>
      <div><h1>{t("invite.loi_moi_tham_gia")}</h1>
        {!inv && !error && <p>{t("invite.dang_kiem_tra_link")}</p>}
        {inv && <p><b>{inv.invited_by || t("invite.quan_tri_vien")}</b> {t("invite.moi")} <b>{inv.email}</b> {t("invite.vao")} <b>{inv.organization}</b>
          {inv.company ? ` · ${inv.company}` : ""}{inv.department ? t("invite.phong", {p0: inv.department}) : ""}
          {" "}{t("invite.voi_vai")} <b>{inv.role_label}</b>{inv.job_title ? ` (${inv.job_title})` : ""}.</p>}</div>
      {inv && <>
        {!inv.account_exists && <Field label={t("invite.ten_hien_thi")}><input name="name" value={name} onChange={e => setName(e.target.value)} placeholder={t("invite.ho_ten_cua_anh_chi")} autoComplete="name"/></Field>}
        <Field label={inv.account_exists ? t("invite.mat_khau_tai_khoan_hien") : t("invite.dat_mat_khau")} hint={inv.account_exists ? undefined : t("invite.it_nhat_8_ky_tu")}>
          <input type="password" name="password" value={pw} autoComplete={inv.account_exists ? "current-password" : "new-password"} onChange={e => setPw(e.target.value)}/></Field>
        {!inv.account_exists && <Field label={t("invite.nhap_lai_mat_khau")} error={formErr || undefined}><input type="password" name="password2" value={pw2} autoComplete="new-password" onChange={e => setPw2(e.target.value)}/></Field>}
      </>}
      {x && <div className="ui-banner is-error" role="alert" data-testid="invite-error"><div><b>{x.title}.</b> {x.detail}
        <span className="ui-banner-fix">{x.fix} {t("invite.link_moi_hong_hoac_het")}</span></div></div>}
      {inv && <Button type="submit" variant="primary" size="lg" block busy={busy} disabled={!pw} data-testid="invite-accept">{busy ? t("invite.dang_vao") : t("invite.nhan_loi_moi")}</Button>}
      <small className="auth-note">{t("invite.link_moi_chi_dung_mot")}</small>
    </form>
    <aside className="auth-art" aria-hidden="true"><BeCang mood="hello" size={200}/><p>{t("invite.vao_la_thay_ngay_so")}</p></aside>
  </div>;
}
