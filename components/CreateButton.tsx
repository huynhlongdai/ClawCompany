"use client";
import Link from "next/link";
import {Icon} from "./Icon";

/* Nút "Tạo mới" của mockup. Mockup vẽ nó mở một menu; ở đây nó dẫn tới
   /app/workspace-ops — nơi duy nhất thật sự tạo được công ty, phòng ban, ghế,
   dự án và nhiệm vụ (13 endpoint ghi của v18). Một menu đẹp mà bấm vào không
   tạo được gì thì tệ hơn là một liên kết đúng chỗ. */
export function CreateButton() {
  return <Link href="/app/workspace-ops" className="v8Primary" style={{textDecoration: "none"}}>
    <Icon name="plus" size={16}/>
    Tạo mới
  </Link>;
}
