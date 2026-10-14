"use client";
import {ReactNode, useState, useSyncExternalStore} from "react";
import {login} from "../lib/auth";
import {explain} from "../lib/errors";
import {Logo, LogoLockup} from "./Logo";
import {BeCang} from "./BeCang";
import {Button} from "./ui/Button";
import {Field} from "./ui/Field";
import {t} from "../lib/i18n";
import {LanguageSwitcher} from "./LanguageSwitcher";

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
  if (state === "checking") return <div className="auth-splash" aria-busy="true" aria-label={t("auth.dang_mo_clawcompany")}><Logo size={44} hole="var(--bg)"/></div>;
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
      const x = explain(Object.assign(new Error(raw), {status, code: status === 0 ? "network" : ""}), t("auth.dang_nhap"));
      setError(status === 401 ? {...x, title: t("auth.sai_email_hoac_mat_khau"), fix: t("auth.kiem_tra_lai_hoac_nho")} : x);
    } finally { setBusy(false); }
  }

  return <div className="auth">
    <form className="auth-card" onSubmit={submit} data-testid="login-form" noValidate>
      <LogoLockup hole="var(--surface)"/>
      <div><h1>{t("auth.dang_nhap")}</h1><p>{t("auth.vao_cong_ty_cua_anh")}</p></div>
      <Field label="Email"><input type="email" name="email" value={email} autoComplete="username" spellCheck={false} inputMode="email"
        onChange={e => setEmail(e.target.value)} placeholder={t("auth.email_ph")} required/></Field>
      <Field label={t("auth.mat_khau")}><input type="password" name="password" value={password} autoComplete="current-password"
        onChange={e => setPassword(e.target.value)} placeholder={t("auth.mat_khau_2")} required/></Field>
      {error && <div className="ui-banner is-error" role="alert"><div><b>{error.title}.</b><span className="ui-banner-fix">{error.fix}</span></div></div>}
      <Button type="submit" variant="primary" size="lg" block busy={busy} data-testid="login-submit">{busy ? t("auth.dang_dang_nhap") : t("auth.dang_nhap")}</Button>
      <div style={{display: "flex", justifyContent: "center"}}><LanguageSwitcher compact saveProfile={false}/></div>
      <small className="auth-note">{t("auth.ban_cai_demo")} <code translate="no">admin@clawcompany.local</code></small>
    </form>
    <aside className="auth-art" aria-hidden="true">
      <BeCang mood="working" size={220}/>
      <p>{t("auth.cua_so_sang_la_agent")}<br/>{t("auth.anh_chi_can_duyet_nhung")}</p>
    </aside>
  </div>;
}
