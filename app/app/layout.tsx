import {AuthGate} from "../../components/AuthGate";
import {Shell} from "../../components/shell/Shell";

/* Một shell cho mọi route /app/* — mount một lần, giữ nguyên khi chuyển trang. */
export default function AppLayout({children}: {children: React.ReactNode}) {
  return <AuthGate><Shell>{children}</Shell></AuthGate>;
}
