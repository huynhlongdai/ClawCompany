"use client";
import {useEffect} from "react";
import {EmptyState} from "../../components/ui/EmptyState";
import {Button, ButtonLink} from "../../components/ui/Button";

/* Ranh giới lỗi cho mọi trang trong shell: trang hỏng không kéo sập menu. */
export default function AppError({error, reset}: {error: Error & {digest?: string}; reset: () => void}) {
  useEffect(() => { console.warn("Trang gặp lỗi khi vẽ:", error?.message); }, [error]);
  return <EmptyState mood="loi" title="Trang này gặp lỗi khi hiển thị"
    action={<div className="ui-confirm-actions"><Button variant="primary" onClick={reset}>Thử lại</Button><ButtonLink href="/app/inbox">Về Hộp việc</ButtonLink></div>}>
    Menu và các trang khác vẫn dùng được. Bấm Thử lại; nếu vẫn lỗi, tải lại trang và gửi ảnh màn hình này cho người quản trị
    {error?.digest ? ` (mã ${error.digest})` : ""}.<br/><small>Chi tiết: {String(error?.message || "không rõ").slice(0, 200)}</small>
  </EmptyState>;
}
