"use client";
import Link from "next/link";
import type {ReactNode} from "react";

/* Tab điều hướng (đổi URL — chia sẻ được, back hoạt động). */
export function LinkTabs({tabs, active, label}: {tabs: {href: string; label: ReactNode; count?: number}[]; active?: string; label: string}) {
  return <nav className="ui-tabs" aria-label={label}>
    {tabs.map(t => <Link key={t.href} href={t.href} className="ui-tab" aria-current={t.href === active ? "page" : undefined} scroll={false}>
      {t.label}{t.count ? <em className="ui-count">{t.count}</em> : null}
    </Link>)}
  </nav>;
}

/* Bộ chọn phân đoạn — state cục bộ, vài lựa chọn ngắn. */
export function Segmented<T extends string>({value, onChange, options, label}: {
  value: T; onChange: (v: T) => void; options: {value: T; label: ReactNode; testId?: string}[]; label: string;
}) {
  return <div className="ui-seg" role="group" aria-label={label}>
    {options.map(o => <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)} data-testid={o.testId}>{o.label}</button>)}
  </div>;
}
