"use client";
import {Suspense} from "react";
import {PageFrame} from "@/components/shell/PageFrame";
import {InboxHub} from "@/components/InboxHub";

/* M4b — Hộp việc trên /api/inbox: nhóm theo việc cần làm, duyệt một chạm (cả trên điện thoại). */
export default function Page() {
  return <PageFrame title="Hộp việc" subtitle="">
    <Suspense fallback={null}><InboxHub/></Suspense>
  </PageFrame>;
}
