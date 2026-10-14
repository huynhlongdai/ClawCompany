"use client";
import {Suspense} from "react";
import {AuthGate} from "@/components/AuthGate";
import {AppShell} from "@/components/AppShell";
import {InboxHub} from "@/components/InboxHub";

/* M4b — Hộp việc trên /api/inbox: nhóm theo việc cần làm, duyệt một chạm (cả trên điện thoại). */
export default function Page() {
  return <AuthGate><AppShell title="Hộp việc" subtitle="">
    <Suspense fallback={null}><InboxHub/></Suspense>
  </AppShell></AuthGate>;
}
