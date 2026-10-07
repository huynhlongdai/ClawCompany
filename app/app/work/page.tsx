"use client";
import {Suspense} from "react";
import {AuthGate} from "@/components/AuthGate";
import {AppShell} from "@/components/AppShell";
import {WorkBoard} from "@/components/WorkBoard";

/* M4a — Công việc: danh sách / bảng / side-peek (?peek=id) trên một nguồn /api/work. */
export default function Page() {
  return <AuthGate><AppShell title="Công việc" subtitle="">
    <Suspense fallback={null}><WorkBoard/></Suspense>
  </AppShell></AuthGate>;
}
