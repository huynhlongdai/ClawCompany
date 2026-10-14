import {redirect} from "next/navigation";

/* Trang gốc dẫn thẳng vào app. Dashboard demo đời cũ (ClawCompanyApp, dữ liệu mẫu) không còn route nào trỏ tới. */
export default function Page() { redirect("/app/os"); }
