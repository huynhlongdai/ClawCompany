"use client";
import {PageFrame} from "@/components/shell/PageFrame";
import {LiveRunsConsole} from "@/components/LiveRunsConsole";

export default function Page(){
  return <PageFrame>
    <LiveRunsConsole/>
  </PageFrame>;
}
