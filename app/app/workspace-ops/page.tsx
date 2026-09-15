"use client";
import {AuthGate} from "@/components/AuthGate";
import {V17AppShell} from "@/components/V17AppShell";
import {WorkspaceOpsConsole} from "@/components/WorkspaceOpsConsole";

export default function Page(){
  return <AuthGate><V17AppShell title="Vận hành tổ chức" subtitle="Lập công ty, phòng ban, nhân sự, agent, dự án và nhiệm vụ — ghi thẳng vào dữ liệu thật">
    <WorkspaceOpsConsole/>
  </V17AppShell></AuthGate>;
}
