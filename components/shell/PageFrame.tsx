"use client";
import {ReactNode, useEffect} from "react";
import {usePathname, useSearchParams} from "next/navigation";
import {LinkTabs} from "../ui/Tabs";
import {StatusPill} from "../ui/StatusPill";
import {activeTab, isLabPath, pageFor, sectionFor} from "../../lib/nav";

/* Khung một trang: tiêu đề + mô tả + nút + tab của mục + (tuỳ chọn) cột phải.

   Tiêu đề và tab lấy từ lib/nav.ts theo đường dẫn — một tên cho mỗi khái niệm,
   kể cả khi console cũ truyền tiêu đề tiếng Anh. Trang chi tiết (/app/tasks/7,
   /app/agents/3) dùng `title` truyền vào và không hiện tab.
   Interface nhỏ: chỉ cần bọc nội dung; mọi thứ khác tự suy ra. */
export function PageFrame({title = "", subtitle = "", action, actions, rail, children, wide, hideHead}: {
  title?: string; subtitle?: string; action?: ReactNode; actions?: ReactNode; rail?: ReactNode; children: ReactNode; wide?: boolean; hideHead?: boolean;
}) {
  const pathname = usePathname();
  const search = useSearchParams();
  const section = sectionFor(pathname);
  const tab = activeTab(section, pathname, search);
  const page = section ? undefined : pageFor(pathname);
  const isTabPage = !!section && section.tabs.some(t => t.href.split("?")[0] === pathname);
  const detail = !!section && !isTabPage && pathname !== section.href;
  const h1 = detail ? (title || section!.label) : section ? section.label : page ? page.label : title;
  const p = detail ? subtitle : section ? section.desc : page ? page.desc : subtitle;
  const lab = isLabPath(pathname);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent("cc:title", {detail: detail ? h1 : page ? page.label : tab && tab !== section?.tabs[0] ? tab.label : section ? "" : h1}));
  }, [h1, detail, page, tab, section]);

  const tabs = !detail && section && section.tabs.length > 1 ? section.tabs : null;
  const body = <div className="ui-page-body">{children}</div>;
  return <>
    {!hideHead && <div className="ui-pagehead">
      <div><h1>{h1}{lab && <> <StatusPill tone="wait">Phòng thí nghiệm</StatusPill></>}</h1>{p && <p>{p}</p>}</div>
      {(action || actions) && <div className="ui-pagehead-actions">{actions}{action}</div>}
    </div>}
    {tabs && <div className="ui-page-tabs"><LinkTabs label={`Các phần của ${section!.label}`} active={tab?.href}
      tabs={tabs.map(t => ({href: t.href, label: t.label}))}/></div>}
    {rail ? <div className={"ui-with-rail" + (wide ? " is-wide" : "")}>{body}<aside aria-label="Thông tin bên">{rail}</aside></div> : body}
  </>;
}

/** Giữ tương thích: các console cũ import AppShell/V*AppShell — nay chỉ là khung trang (shell nằm trong layout). */
export const AppShell = PageFrame;
