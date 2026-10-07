"use client";
// M2 — nhận lời mời: xem ai mời, vào đâu, vai gì; đặt mật khẩu (hoặc nhập mật
// khẩu tài khoản sẵn có) rồi vào thẳng trang Đội ngũ với đúng quyền.
import {useEffect, useState} from "react";
import {useParams, useRouter} from "next/navigation";
import {apiTeam, errorText} from "../../../lib/api";
import {LogoLockup} from "../../../components/Logo";

export default function InvitePage() {
  const {token} = useParams<{token: string}>();
  const router = useRouter();
  const [inv, setInv] = useState<any>(null), [error, setError] = useState("");
  const [name, setName] = useState(""), [pw, setPw] = useState(""), [pw2, setPw2] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    apiTeam.lookupInvite(token).then(x => { setInv(x); setName(x.display_name || ""); }).catch(e => setError(errorText(e)));
  }, [token]);
  async function accept() {
    setError("");
    if (!inv.account_exists && pw !== pw2) { setError("Hai lần nhập mật khẩu chưa khớp"); return; }
    setBusy(true);
    try {
      const r = await apiTeam.acceptInvite(token, pw, name);
      localStorage.setItem("clawcompany_token", r.access_token);
      router.replace("/app/team");
    } catch (e: any) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <div className="portalLogin">
    <div className="portalLoginCard" data-testid="invite-card">
      <LogoLockup hole="#ffffff" dark={false}/>
      <h1>Lời mời tham gia</h1>
      {!inv && !error && <p>Đang kiểm tra link…</p>}
      {inv && <>
        <p><b>{inv.invited_by || "Quản trị viên"}</b> mời <b>{inv.email}</b> vào <b>{inv.organization}</b>
          {inv.company ? ` · ${inv.company}` : ""}{inv.department ? ` · phòng ${inv.department}` : ""}
          {" "}với vai <b>{inv.role_label}</b>{inv.job_title ? ` (${inv.job_title})` : ""}.</p>
        {!inv.account_exists && <>
          <label htmlFor="iv-name">Tên hiển thị</label>
          <input id="iv-name" value={name} onChange={e => setName(e.target.value)} placeholder="Họ tên của bạn"/>
        </>}
        <label htmlFor="iv-pw">{inv.account_exists ? "Mật khẩu tài khoản hiện có" : "Đặt mật khẩu (ít nhất 8 ký tự)"}</label>
        <input id="iv-pw" type="password" value={pw} autoComplete={inv.account_exists ? "current-password" : "new-password"}
               onChange={e => setPw(e.target.value)} onKeyDown={e => e.key === "Enter" && inv.account_exists && accept()}/>
        {!inv.account_exists && <>
          <label htmlFor="iv-pw2">Nhập lại mật khẩu</label>
          <input id="iv-pw2" type="password" value={pw2} autoComplete="new-password" onChange={e => setPw2(e.target.value)}
                 onKeyDown={e => e.key === "Enter" && accept()}/>
        </>}
      </>}
      {error && <div className="portalError" style={{marginTop: 12}} data-testid="invite-error">{error}</div>}
      {inv && <button onClick={accept} disabled={busy || !pw} data-testid="invite-accept">{busy ? "Đang vào…" : "Nhận lời mời"}</button>}
      <small style={{display: "block", marginTop: 14, textAlign: "center"}}>Link mời chỉ dùng một lần và hết hạn sau 7 ngày.</small>
    </div>
  </div>;
}
