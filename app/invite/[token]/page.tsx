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
    if (!inv.account_exists && pw.length < 8) { setFormErr("Mật khẩu cần ít nhất 8 ký tự."); return; }
    if (!inv.account_exists && pw !== pw2) { setFormErr("Hai lần nhập mật khẩu chưa khớp — nhập lại ô thứ hai."); return; }
    setBusy(true);
    try {
      const r = await apiTeam.acceptInvite(token, pw, name);
      localStorage.setItem("clawcompany_token", r.access_token);
      router.replace("/app/team");
    } catch (e: any) { setError(e); } finally { setBusy(false); }
  }
  const x = error ? explain(error, "Nhận lời mời") : null;
  return <div className="auth">
    <form className="auth-card" data-testid="invite-card" onSubmit={e => { e.preventDefault(); accept(); }} noValidate>
      <LogoLockup/>
      <div><h1>Lời mời tham gia</h1>
        {!inv && !error && <p>Đang kiểm tra link…</p>}
        {inv && <p><b>{inv.invited_by || "Quản trị viên"}</b> mời <b>{inv.email}</b> vào <b>{inv.organization}</b>
          {inv.company ? ` · ${inv.company}` : ""}{inv.department ? ` · phòng ${inv.department}` : ""}
          {" "}với vai <b>{inv.role_label}</b>{inv.job_title ? ` (${inv.job_title})` : ""}.</p>}</div>
      {inv && <>
        {!inv.account_exists && <Field label="Tên hiển thị"><input name="name" value={name} onChange={e => setName(e.target.value)} placeholder="Họ tên của anh/chị…" autoComplete="name"/></Field>}
        <Field label={inv.account_exists ? "Mật khẩu tài khoản hiện có" : "Đặt mật khẩu"} hint={inv.account_exists ? undefined : "Ít nhất 8 ký tự"}>
          <input type="password" name="password" value={pw} autoComplete={inv.account_exists ? "current-password" : "new-password"} onChange={e => setPw(e.target.value)}/></Field>
        {!inv.account_exists && <Field label="Nhập lại mật khẩu" error={formErr || undefined}><input type="password" name="password2" value={pw2} autoComplete="new-password" onChange={e => setPw2(e.target.value)}/></Field>}
      </>}
      {x && <div className="ui-banner is-error" role="alert" data-testid="invite-error"><div><b>{x.title}.</b> {x.detail}
        <span className="ui-banner-fix">{x.fix} Link mời hỏng hoặc hết hạn thì nhờ người mời tạo link mới.</span></div></div>}
      {inv && <Button type="submit" variant="primary" size="lg" block busy={busy} disabled={!pw} data-testid="invite-accept">{busy ? "Đang vào…" : "Nhận lời mời"}</Button>}
      <small className="auth-note">Link mời chỉ dùng một lần và hết hạn sau 7 ngày.</small>
    </form>
    <aside className="auth-art" aria-hidden="true"><BeCang mood="hello" size={200}/><p>Vào là thấy ngay sơ đồ đội ngũ — người và agent cùng một công ty.</p></aside>
  </div>;
}
