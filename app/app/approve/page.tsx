"use client";
import {useEffect} from "react";
import {useRouter} from "next/navigation";

/* M4b: "Duyệt nhanh" cũ gộp vào Hộp việc (nhóm Cần anh duyệt — chạy ở 390px). Giữ đường để link cũ không gãy. */
export default function Page() {
  const router = useRouter();
  useEffect(() => { router.replace("/app/inbox?group=approvals"); }, [router]);
  return null;
}
