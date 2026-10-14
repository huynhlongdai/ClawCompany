/* Logo ClawCompany — bản đã chốt ở design/brand/ (plan-v2 §6): chữ C hình chiếc
   càng nắm 3 chấm (Đèn = việc, Rong = agent, Càng/Kem = người).

   Vẽ inline (không tải ảnh) và đổi bản theo giao diện bằng biến CSS:
   nền sáng dùng logo-light (ô Kem, càng Mực), nền tối dùng logo-dark (ô Mực, càng
   Càng). Biến khai ở app/styles/brand.css. `hole` giữ lại cho tương thích, không dùng. */

export function Logo({size = 34}: {size?: number; hole?: string; rounded?: boolean}) {
  return <svg width={size} height={size} viewBox="0 0 512 512" role="img" aria-label="ClawCompany" style={{display: "block", flex: "none"}}>
    <rect width="512" height="512" rx="112" fill="var(--logo-tile)"/>
    <path d="M386.2 146.7 A170 170 0 1 0 386.2 365.3 Q396 322 377.3 286.2 L322.2 319.9 A92 92 0 1 1 322.2 192.1 L377.3 225.8 Q396 190 386.2 146.7 Z"
          fill="var(--logo-claw)" stroke="var(--logo-claw)" strokeWidth="12" strokeLinejoin="round"/>
    <circle cx="232" cy="212" r="26" fill="#FFD36B"/><circle cx="302" cy="256" r="26" fill="#16B3A3"/><circle cx="232" cy="300" r="26" fill="var(--logo-dot)"/>
  </svg>;
}

/* Logo kèm chữ — cửa đăng nhập, lời mời, onboarding. */
export function LogoLockup({subtitle = "Điều hành công ty cùng đội agent"}: {hole?: string; subtitle?: string; dark?: boolean}) {
  return <span className="logo-lockup">
    <Logo size={40}/>
    <span><b translate="no">ClawCompany</b><small>{subtitle}</small></span>
  </span>;
}
