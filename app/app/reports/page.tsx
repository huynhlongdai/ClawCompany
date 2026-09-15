import {AuthGate} from "../../../components/AuthGate";
import {V17AppShell} from "../../../components/V17AppShell";
import {ReportsConsole} from "../../../components/ReportsConsole";

export default function Page() {
  return <AuthGate>
    <V17AppShell title="Báo cáo" subtitle="Chỉ số tổ chức có trị hiện tại, kỳ trước và mục tiêu — cùng các báo cáo đã sinh">
      <ReportsConsole/>
    </V17AppShell>
  </AuthGate>;
}
