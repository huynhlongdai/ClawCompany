"use client";
import Link from "next/link";
import type {ButtonHTMLAttributes, ReactNode} from "react";
import {Icon, IconName} from "../Icon";

/* Nút: một interface cho mọi biến thể. `busy` giữ chiều rộng, hiện vòng quay, khoá nút. */
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant; size?: "sm" | "md" | "lg"; icon?: IconName; busy?: boolean; block?: boolean; kbd?: string;
};
export function cx(...parts: (string | false | null | undefined)[]) { return parts.filter(Boolean).join(" "); }
export function btnClass(variant: Variant = "secondary", size: "sm" | "md" | "lg" = "md", block = false) {
  return cx("ui-btn", variant !== "secondary" && `is-${variant}`, size !== "md" && `is-${size}`, block && "is-block");
}

export function Button({variant = "secondary", size = "md", icon, busy, block, kbd, children, className, disabled, type = "button", ...rest}: Props) {
  return <button type={type} className={cx(btnClass(variant, size, block), className)} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
    {busy ? <span className="ui-spin" aria-hidden="true"/> : icon ? <Icon name={icon} size={size === "sm" ? 14 : 16}/> : null}
    {children}
    {kbd && <kbd aria-hidden="true">{kbd}</kbd>}
  </button>;
}

export function ButtonLink({href, variant = "secondary", size = "md", icon, children, className}: {
  href: string; variant?: Variant; size?: "sm" | "md" | "lg"; icon?: IconName; children: ReactNode; className?: string;
}) {
  return <Link href={href} className={cx(btnClass(variant, size), className)}>
    {icon && <Icon name={icon} size={size === "sm" ? 14 : 16}/>}{children}
  </Link>;
}

export function IconButton({icon, label, size = "md", ...rest}: ButtonHTMLAttributes<HTMLButtonElement> & {icon: IconName; label: string; size?: "sm" | "md"}) {
  return <button type="button" className={cx("ui-iconbtn", size === "sm" && "is-sm")} aria-label={label} title={label} {...rest}>
    <Icon name={icon} size={size === "sm" ? 15 : 17}/>
  </button>;
}
