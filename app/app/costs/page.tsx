"use client";
import {Suspense} from "react";
import {PageFrame} from "@/components/shell/PageFrame";
import {CostsBoard} from "@/components/CostsBoard";

/* M4b — Chi phí: tổng chi model + ngân sách 3 nấc (cảnh báo → dừng mềm cần duyệt → dừng cứng). */
export default function Page() {
  return <PageFrame>
    <Suspense fallback={null}><CostsBoard/></Suspense>
  </PageFrame>;
}
