"use client";
import {AuthGate} from "@/components/AuthGate";
import {V17AppShell} from "@/components/V17AppShell";
import {WorkFlowBoard} from "@/components/WorkFlowBoard";

export default function Page(){
  return <AuthGate><V17AppShell title="Work Flow" subtitle="Thời gian nằm trong mỗi trạng thái của vòng đời nhiệm vụ — việc quá target nổi lên trước">
    <WorkFlowBoard/>
  </V17AppShell></AuthGate>;
}
