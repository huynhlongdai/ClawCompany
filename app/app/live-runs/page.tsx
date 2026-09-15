"use client";
import {AuthGate} from "@/components/AuthGate";
import {V17AppShell} from "@/components/V17AppShell";
import {LiveRunsConsole} from "@/components/LiveRunsConsole";

export default function Page(){
  return <AuthGate><V17AppShell title="Phiên đang chạy" subtitle="Theo dõi phiên OpenClaw dài hạn, chuyển trạng thái nhiệm vụ và hàng đợi phê duyệt từ gateway">
    <LiveRunsConsole/>
  </V17AppShell></AuthGate>;
}
