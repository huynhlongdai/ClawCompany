"use client";
import {Suspense} from "react";
import {AuthGate} from "@/components/AuthGate";
import {AppShell} from "@/components/AppShell";
import {CostsBoard} from "@/components/CostsBoard";

/* M4b — Chi phí: tổng chi model + ngân sách 3 nấc (cảnh báo → dừng mềm cần duyệt → dừng cứng). */
export default function Page() {
  return <AuthGate><AppShell title="Chi phí" subtitle="">
    <Suspense fallback={null}><CostsBoard/></Suspense>
  </AppShell></AuthGate>;
}
