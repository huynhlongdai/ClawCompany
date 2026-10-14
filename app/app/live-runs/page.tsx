"use client";
import {PageFrame} from "@/components/shell/PageFrame";
import {LiveRunsConsole} from "@/components/LiveRunsConsole";

export default function Page(){
  return <PageFrame title="Phiên đang chạy" subtitle="Theo dõi phiên OpenClaw dài hạn, chuyển trạng thái nhiệm vụ và hàng đợi phê duyệt từ gateway">
    <LiveRunsConsole/>
  </PageFrame>;
}
