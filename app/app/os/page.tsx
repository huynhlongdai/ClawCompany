"use client";
import {useEffect} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {PageFrame} from "@/components/shell/PageFrame";
import {TodayOverview} from "@/components/overview/TodayOverview";

/* Tổng quan. Link cũ /app/os?tab=… (UI v6) chuyển về chỗ mới trong 8 mục menu. */
const MOVED: Record<string, string> = {
  projects: "/app/work?view=projects", tasks: "/app/work", agents: "/app/team?tab=ai", people: "/app/team?tab=people",
  companies: "/app/team", knowledge: "/app/knowledge-mesh",
};

export default function Page() {
  const tab = useSearchParams().get("tab") || "";
  const router = useRouter();
  useEffect(() => { if (MOVED[tab]) router.replace(MOVED[tab]); }, [tab, router]);
  if (MOVED[tab]) return null;
  return <PageFrame><TodayOverview/></PageFrame>;
}
