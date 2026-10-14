"use client";
import type {ReactNode} from "react";
import {BeCang, BeCangMood} from "../BeCang";
import {explain} from "../../lib/errors";
import {Button} from "./Button";
import {Icon} from "../Icon";
import {t} from "../../lib/i18n";

/* Trạng thái rỗng/lỗi có Bé Càng — 5 trạng thái theo plan §6:
   chào (mới bắt đầu), làm việc (đang chạy), duyệt xong (hết việc), lỗi, ngủ (trống, chưa có gì). */
export type Mood = "chao" | "lam-viec" | "duyet-xong" | "loi" | "ngu";
const MOOD: Record<Mood, BeCangMood> = {"chao": "hello", "lam-viec": "working", "duyet-xong": "done", "loi": "error", "ngu": "sleep"};

export function EmptyState({mood = "ngu", title, children, action, compact, testId}: {
  mood?: Mood; title: string; children?: ReactNode; action?: ReactNode; compact?: boolean; testId?: string;
}) {
  return <div className={"bc-state" + (mood === "loi" ? " is-error" : "") + (compact ? " ui-empty is-compact" : "")}
              role={mood === "loi" ? "alert" : "status"} data-testid={testId}>
    <BeCang mood={MOOD[mood]} size={compact ? 64 : 88}/>
    <b>{title}</b>
    {children && <span>{children}</span>}
    {action}
  </div>;
}

/* Lỗi tải dữ liệu: câu giải thích + cách xử lý + nút Thử lại. */
export function ErrorState({error, onRetry, context, compact}: {error: unknown; onRetry?: () => void; context?: string; compact?: boolean}) {
  const x = explain(error, context);
  return <EmptyState mood="loi" title={x.title} compact={compact}
    action={onRetry && x.retry ? <Button variant="primary" icon="arrow-right" onClick={onRetry}>{t("ui.thu_lai")}</Button> : undefined}>
    {x.fix}{x.detail && x.detail !== x.title ? <><br/><small style={{opacity: .85}}>{t("ui.chi_tiet")} {x.detail}</small></> : null}
  </EmptyState>;
}

/* Lỗi một thao tác (không thay cả trang): dải báo trên đầu khu vực. */
export function ErrorBanner({error, onRetry, onClose, context, testId}: {error: unknown; onRetry?: () => void; onClose?: () => void; context?: string; testId?: string}) {
  const x = explain(error, context);
  return <div className="ui-banner is-error" role="alert" data-testid={testId}>
    <Icon name="alert" size={16}/>
    <div><b>{x.title}.</b> {x.detail && x.detail !== x.title ? x.detail : ""}<span className="ui-banner-fix">{x.fix}</span></div>
    {onRetry && x.retry && <Button size="sm" variant="ghost" onClick={onRetry}>{t("ui.thu_lai")}</Button>}
    {onClose && <Button size="sm" variant="ghost" onClick={onClose}>{t("ui.dong")}</Button>}
  </div>;
}

export function Notice({tone = "info", children, testId}: {tone?: "info" | "ok" | "wait" | "error"; children: ReactNode; testId?: string}) {
  return <div className={"ui-banner" + (tone !== "info" ? " is-" + tone : "")} role={tone === "error" ? "alert" : "status"} data-testid={testId}>
    <Icon name={tone === "ok" ? "check" : tone === "error" || tone === "wait" ? "alert" : "bell"} size={16}/><div>{children}</div>
  </div>;
}
