"use client";
import {AuthGate} from "@/components/AuthGate";
import {AppShell} from "@/components/AppShell";
import {WorkFlowBoard} from "@/components/WorkFlowBoard";

export default function Page(){
  return <AuthGate><AppShell title="Bảng việc" subtitle="">
    <WorkFlowBoard/>
  </AppShell></AuthGate>;
}
