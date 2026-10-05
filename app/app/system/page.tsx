"use client";
import {AuthGate} from "@/components/AuthGate";
import {AppShell} from "@/components/AppShell";
import {SystemDirectory} from "@/components/SystemDirectory";

export default function Page() {
  return <AuthGate><AppShell title="Danh bạ công cụ" subtitle="">
    <SystemDirectory/>
  </AppShell></AuthGate>;
}
