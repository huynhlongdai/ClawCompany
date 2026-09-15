"use client";
import {AuthGate} from "@/components/AuthGate";
import {V17AppShell} from "@/components/V17AppShell";
import {OpenClawControl} from "@/components/OpenClawControl";

export default function Page(){
  return <AuthGate><V17AppShell title="Lõi OpenClaw" subtitle="Gateway thật, phiên làm việc theo agent, đối soát nhân sự AI và ranh giới công cụ">
    <OpenClawControl/>
  </V17AppShell></AuthGate>;
}
