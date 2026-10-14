"use client";
import {PageFrame} from "@/components/shell/PageFrame";
import {OpenClawControl} from "@/components/OpenClawControl";

export default function Page(){
  return <PageFrame title="Lõi OpenClaw" subtitle="Gateway thật, phiên làm việc theo agent, đối soát nhân sự AI và ranh giới công cụ">
    <OpenClawControl/>
  </PageFrame>;
}
