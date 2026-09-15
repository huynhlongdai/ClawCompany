/* Logo ClawCompany.
   Dựng lại theo mẫu người dùng gửi: một khối "gem" bốn cạnh với hai góc đối
   diện vê tròn mạnh, tô gradient xanh dương -> tím, khoét một lỗ lục giác ở
   giữa. Vẽ bằng SVG thay vì ảnh bitmap để nó nét ở mọi kích thước, đổi màu
   theo ngữ cảnh được, và không thêm một request tải ảnh nào.

   `hole` là màu lỗ khoét ở giữa: trên sidebar tối thì truyền màu sidebar, trên
   thẻ trắng thì truyền trắng — vì đây là lỗ thật, không phải hình tròn màu. */

export function Logo({size = 34, hole = "#12141f", rounded = true}: {
  size?: number; hole?: string; rounded?: boolean;
}) {
  const id = `cc-logo-${size}-${hole.replace("#", "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-label="ClawCompany"
         style={{display: "block", flex: "none"}}>
      <defs>
        <linearGradient id={id} x1="6" y1="4" x2="34" y2="36" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#8fb6ff"/>
          <stop offset="0.45" stopColor="#6d7dff"/>
          <stop offset="1" stopColor="#6d34f2"/>
        </linearGradient>
      </defs>
      {/* Thân: hình vuông vê góc không đều — hai góc trên-trái và dưới-phải
          vê mạnh (12), hai góc còn lại vê nhẹ (4). Đúng dáng "hạt" của mẫu. */}
      <path
        d={rounded
          ? "M16 2h18a4 4 0 0 1 4 4v18c0 7.7-6.3 14-14 14H6a4 4 0 0 1-4-4V16C2 8.3 8.3 2 16 2Z"
          : "M2 2h36v36H2Z"}
        fill={`url(#${id})`}
      />
      {/* Lỗ lục giác ở giữa, hơi lệch trái như mẫu. */}
      <path d="M19 12.4l6.2 3.6v7.2L19 26.8l-6.2-3.6V16L19 12.4Z" fill={hole}/>
    </svg>
  );
}

/* Logo kèm chữ, dùng ở sidebar và cửa đăng nhập. */
export function LogoLockup({hole = "#12141f", subtitle = "AI Organization OS", dark = true}: {
  hole?: string; subtitle?: string; dark?: boolean;
}) {
  return (
    <span style={{display: "flex", alignItems: "center", gap: 11}}>
      <Logo size={34} hole={hole}/>
      <span>
        <b style={{
          display: "block", fontSize: 16, fontWeight: 700, letterSpacing: "-.02em",
          color: dark ? "#fff" : "var(--ink)",
        }}>ClawCompany</b>
        <small style={{display: "block", fontSize: 11, color: dark ? "#8f97b3" : "var(--muted)"}}>
          {subtitle}
        </small>
      </span>
    </span>
  );
}
