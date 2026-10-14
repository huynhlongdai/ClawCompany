"use client";
import {PageFrame} from "@/components/shell/PageFrame";
import {WorkspaceOpsConsole} from "@/components/WorkspaceOpsConsole";

export default function Page(){
  return <PageFrame title="Vận hành tổ chức" subtitle="Lập công ty, phòng ban, nhân sự, agent, dự án và nhiệm vụ — ghi thẳng vào dữ liệu thật">
    <WorkspaceOpsConsole/>
  </PageFrame>;
}
