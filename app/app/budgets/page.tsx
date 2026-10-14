"use client";
import {useEffect} from "react";
import {useRouter} from "next/navigation";

/* M4b: trang Ngân sách cũ (v9) gộp vào Chi phí → tab Ngân sách. Giữ đường để link cũ không gãy. */
export default function Page() {
  const router = useRouter();
  useEffect(() => { router.replace("/app/costs?tab=budgets"); }, [router]);
  return null;
}
