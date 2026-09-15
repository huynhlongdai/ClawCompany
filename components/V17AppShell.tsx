"use client";
import Link from "next/link";
import {usePathname, useSearchParams} from "next/navigation";
import {ReactNode, Suspense} from "react";
import {Icon, IconName} from "./Icon";

/* Vỏ ứng dụng — Screen 01 của design canvas v17.
   Ba thay đổi so với bản trước: icon là SVG (ký tự Unicode render thành ô
   vuông trên Linux), mục đang xem được đánh dấu theo pathname thật, và
   sidebar phủ hết chiều cao trang kể cả khi nội dung dài hơn màn hình. */

type NavItem = {icon: IconName; label: string; href: string};

const GROUPS: [string, NavItem[]][] = [
  ["Tổ chức", [
    {icon: "home", label: "Trang chủ", href: "/app/os"},
    {icon: "building", label: "Công ty", href: "/app/os?tab=companies"},
    {icon: "users", label: "Nhân sự", href: "/app/os?tab=people"},
    {icon: "sparkle", label: "AI Agents", href: "/app/os?tab=agents"},
  ]],
  ["Vận hành", [
    {icon: "board", label: "Dự án", href: "/app/os?tab=projects"},
    {icon: "check", label: "Nhiệm vụ", href: "/app/os?tab=tasks"},
    {icon: "book", label: "Kiến thức", href: "/app/os?tab=knowledge"},
    {icon: "pencil", label: "Vận hành tổ chức", href: "/app/workspace-ops"},
  ]],
  ["Phối hợp agent", [
    {icon: "room", label: "Collaboration Fabric", href: "/app/collaboration"},
    {icon: "mesh", label: "Knowledge Mesh", href: "/app/knowledge-mesh"},
    {icon: "crown", label: "Nina SRE Control", href: "/app/sre-control"},
    {icon: "gear", label: "Lõi OpenClaw", href: "/app/openclaw"},
    {icon: "pulse", label: "Phiên đang chạy", href: "/app/live-runs"},
  ]],
];

/* useSearchParams buộc Next phải bỏ prerender tĩnh nếu không có ranh giới
   Suspense -- `next build` báo thẳng:
     "useSearchParams() should be wrapped in a suspense boundary"
   và 4 trang dùng vỏ này đều vỡ lúc export. Nên phần đọc query param nằm
   riêng trong NavGroups, còn vỏ ngoài không chạm tới nó. Fallback là đúng bộ
   nav nhưng chưa biết tab nào -- người dùng không thấy khoảng trống. */
function NavGroups({currentTab}: {currentTab: string}) {
  const pathname = usePathname();
  return <>
    {GROUPS.map(([label, items]) => <div key={label}>
      <div className="v8NavLabel">{label}</div>
      <nav>
        {items.map(item => {
          const [base, query = ""] = item.href.split("?");
          // /app/os dùng ?tab= để chọn màn hình, nên "đang xem" phải so cả
          // tab. Nếu chỉ so pathname thì "Trang chủ" luôn sáng kể cả khi
          // người dùng đang ở tab AI Agents.
          const itemTab = query.startsWith("tab=") ? query.slice(4) : "";
          const active = pathname === base && itemTab === currentTab;
          return <Link key={item.href} href={item.href} className={`v8Nav${active ? " active" : ""}`}>
            <i><Icon name={item.icon}/></i>
            <span>{item.label}</span>
          </Link>;
        })}
      </nav>
    </div>)}
  </>;
}

function NavGroupsWithTab() {
  const params = useSearchParams();
  return <NavGroups currentTab={params.get("tab") || ""}/>;
}

export function V17AppShell({title, subtitle, action, children}: {
  title: string; subtitle: string; action?: ReactNode; children: ReactNode;
}) {
  return <div className="v8Shell">
    <aside className="v8Side">
      <Link href="/app/os" className="v8Brand">
        <span className="brandMark"/>
        <span>
          <b>ClawCompany</b>
          <small>AI Organization OS</small>
        </span>
      </Link>

      <Suspense fallback={<NavGroups currentTab=""/>}>
        <NavGroupsWithTab/>
      </Suspense>

      <div className="v8SideFoot">
        <span className="crown"><Icon name="crown" size={16}/></span>
        <div>
          <b>Nova Holding</b>
          <small>Nina · AI Chief of Staff</small>
        </div>
      </div>
    </aside>

    <main className="v8Main">
      <header className="v8Top">
        <div style={{minWidth: 0}}>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <div className="v8TopActions">{action}</div>
      </header>
      <div className="v8Content">{children}</div>
    </main>
  </div>;
}
