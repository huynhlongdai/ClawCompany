"use client";
import {Suspense} from "react";
import {useSearchParams} from "next/navigation";
import {HomeRail} from "./HomeRail";

/* Rail chỉ thuộc về trang Tổng quan. Các tab /app/os?tab=… là danh sách
   rộng (bảng nhân sự, dự án) nên trả lại chiều ngang cho nội dung. */
function Inner() {
  return useSearchParams().get("tab") ? null : <HomeRail/>;
}
export function HomeRailIfHome() {
  return <Suspense fallback={null}><Inner/></Suspense>;
}
