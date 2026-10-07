"use client";
import {useEffect} from "react";
import {useRouter} from "next/navigation";

/* M4a: "Bảng việc" cũ gộp vào Công việc (kiểu xem Bảng). Giữ đường cũ để link/bookmark không gãy. */
export default function Page() {
  const router = useRouter();
  useEffect(() => { router.replace("/app/work?view=board"); }, [router]);
  return null;
}
