"use client";
import {AuthGate} from "@/components/AuthGate";
import {AppShell} from "@/components/AppShell";
import {InboxConsole} from "@/components/InboxConsole";

export default function Page() {
  return <AuthGate><AppShell title="Hộp việc" subtitle="">
    <InboxConsole/>
  </AppShell></AuthGate>;
}
