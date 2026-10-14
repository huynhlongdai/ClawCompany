"use client";
import {PageFrame} from "@/components/shell/PageFrame";
import {OpenClawControl} from "@/components/OpenClawControl";

export default function Page(){
  return <PageFrame>
    <OpenClawControl/>
  </PageFrame>;
}
