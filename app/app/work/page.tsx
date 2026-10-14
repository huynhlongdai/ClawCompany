"use client";
import {Suspense} from "react";
import {PageFrame} from "@/components/shell/PageFrame";
import {WorkBoard} from "@/components/WorkBoard";

/* M4a — Công việc: danh sách / bảng / side-peek (?peek=id) trên một nguồn /api/work. */
export default function Page() {
  return <PageFrame>
    <Suspense fallback={null}><WorkBoard/></Suspense>
  </PageFrame>;
}
