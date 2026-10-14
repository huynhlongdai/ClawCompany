"use client";
import {ReactNode, useState, useSyncExternalStore} from "react";
import {login} from "../lib/auth";
import {explain} from "../lib/errors";
import {Logo, LogoLockup} from "./Logo";
import {BeCang} from "./BeCang";
import {Button} from "./ui/Button";
import {Field} from "./ui/Field";

/* Cửa đăng nhập. Nằm trong app/app/layout.tsx nên bọc mọi trang /app/* đúng
   một lần (trước v2: mỗi trang tự bọc, có trang bọc hai lần).

   Đọc token bằng useSyncExternalStore: server và lần vẽ đầu ở client đều ra
   trạng thái "đang kiểm tra" (màn chờ có logo), không còn nháy form đăng nhập
   rồi mới vào app như bản cũ. */

const sub = (fn: () => void) => { window.addEventListener("storage", fn); window.addEventListener("cc:auth", fn); return () => { window.removeEventListener("storage", fn); window.removeEventListener("cc:auth", fn); }; };
const snap = () => { try { return localStorage.getItem("clawcompany_token") ? "in" : "out"; } catch { return "out"; } };

export function AuthGate({children}: {children: ReactNode}) {
  const required = process.env.NEXT_PUBLIC_AUTH_REQUIRED === "true";
  const state = useSyncExternalStore(sub, snap, () => "checking");
  if (!required || state === "in") return <>{children}</>;
  if (state === "checking") return <div className="auth-splash" aria-busy="true" aria-label="Đang mở ClawCompany…"><Logo size={44} hole="var(--bg)"/></div>;
  return <LoginScreen/>;
}

export function LoginScreen({onDone}: {onDone?: () => void}) {
  const [email, setEmail] = useState("admin@clawcompany.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [error, setError] = useState<ReturnType<typeof explain> | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await login(email.trim(), password);
      window.dispatchEvent(new Event("cc:auth"));
      onDone?.();
    } catch (err: any) {
      const raw = String(err?.message || err);
      const status = /401|invalid credentials/i.test(raw) ? 401 : /failed to fetch|network/i.test(raw) ? 0 : 500;
      const x = explain(Object.assign(new Error(raw), {status, code: status === 0 ? "network" : ""}), "Đăng nhập");
      setError(status === 401 ? {...x, title: "Sai email hoặc mật khẩu", fix: "Kiểm tra lại, hoặc nhờ người quản trị gửi lời mời mới."} : x);
    } finally { setBusy(false); }
  }

  return <div className="auth">
    <form className="auth-card" onSubmit={submit} data-testid="login-form" noValidate>
      <LogoLockup hole="var(--surface)"/>
      <div><h1>Đăng nhập</h1><p>Vào công ty của anh và đội agent đang làm việc.</p></div>
      <Field label="Email"><input type="email" name="email" value={email} autoComplete="username" spellCheck={false} inputMode="email"
        onChange={e => setEmail(e.target.value)} placeholder="ban@congty.vn…" required/></Field>
      <Field label="Mật khẩu"><input type="password" name="password" value={password} autoComplete="current-password"
        onChange={e => setPassword(e.target.value)} placeholder="Mật khẩu…" required/></Field>
      {error && <div className="ui-banner is-error" role="alert"><div><b>{error.title}.</b><span className="ui-banner-fix">{error.fix}</span></div></div>}
      <Button type="submit" variant="primary" size="lg" block busy={busy} data-testid="login-submit">{busy ? "Đang đăng nhập…" : "Đăng nhập"}</Button>
      <small className="auth-note">Bản cài demo: <code translate="no">admin@clawcompany.local</code></small>
    </form>
    <aside className="auth-art" aria-hidden="true">
      <BeCang mood="working" size={220}/>
      <p>Cửa sổ sáng là agent đang làm.<br/>Anh chỉ cần duyệt những việc quan trọng.</p>
    </aside>
  </div>;
}
