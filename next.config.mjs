// API_PROXY_TARGET (vd. http://api:8000): phục vụ /api/* cùng origin với web,
// để chỉ cần mở MỘT cổng (3000) — dùng khi deploy lên box Prized / sau reverse proxy.
// Khi đó đặt NEXT_PUBLIC_API_BASE=/api. Không đặt thì giữ nguyên hành vi cũ.
const target = process.env.API_PROXY_TARGET;
const nextConfig = target
  ? { async rewrites() { return [{ source: "/api/:path*", destination: `${target}/api/:path*` }]; } }
  : {};
export default nextConfig;
