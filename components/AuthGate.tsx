"use client";
import {useEffect, useState} from "react";
import {login, token} from "../lib/auth";
import {Icon} from "./Icon";
import {LogoLockup} from "./Logo";

/* Cửa đăng nhập — màn hình đầu tiên ai cũng thấy, nên nó phải nói cùng ngôn
   ngữ với phần còn lại. Bản trước dùng inline style với gradient tím, không
   liên quan gì tới design canvas; nay dùng class .portalLogin* của design
   system. */

export function AuthGate({children}: {children: React.ReactNode}) {
  const required = process.env.NEXT_PUBLIC_AUTH_REQUIRED === "true";
  const [authed, setAuthed] = useState(!required);
  useEffect(() => { if (required && token()) setAuthed(true); }, [required]);

  const [email, setEmail] = useState("admin@clawcompany.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true); setError("");
    try {
      await login(email, password);
      setAuthed(true);
    } catch (e: any) {
      // Thông báo lỗi của FastAPI là JSON dài; cắt cho người đọc được.
      const raw = String(e?.message || e);
      setError(raw.length > 180 ? raw.slice(0, 180) + "…" : raw);
    } finally { setBusy(false); }
  }

  if (authed) return <>{children}</>;

  return <div className="portalLogin">
    <div className="portalLoginCard">
      <LogoLockup hole="#ffffff" dark={false}/>

      <h1>Đăng nhập</h1>
      <p>Công ty của bạn, vận hành cùng đội agent.</p>

      <label htmlFor="cc-email">Email</label>
      <input id="cc-email" value={email} autoComplete="username"
             onChange={e => setEmail(e.target.value)}
             onKeyDown={e => e.key === "Enter" && submit()}
             placeholder="ban@congty.com"/>

      <label htmlFor="cc-password">Mật khẩu</label>
      <input id="cc-password" value={password} type="password" autoComplete="current-password"
             onChange={e => setPassword(e.target.value)}
             onKeyDown={e => e.key === "Enter" && submit()}
             placeholder="••••••••"/>

      {error && <div className="portalError" style={{marginTop: 12}}>{error}</div>}

      <button onClick={submit} disabled={busy}>
        {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        {!busy && <Icon name="arrow-right" size={16}/>}
      </button>

      <small style={{display: "block", marginTop: 14, textAlign: "center"}}>
        Bản cài demo dùng <code>admin@clawcompany.local</code>
      </small>
    </div>
  </div>;
}
