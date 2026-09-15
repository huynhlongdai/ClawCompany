import {AuthGate} from "../../../components/AuthGate";
import {V17AppShell} from "../../../components/V17AppShell";
import {MarketplaceConsole} from "../../../components/MarketplaceConsole";

export default function Page() {
  return <AuthGate>
    <V17AppShell title="Marketplace" subtitle="Mẫu công ty, mẫu nhân sự AI và quy trình — cài vào tổ chức của bạn">
      <MarketplaceConsole/>
    </V17AppShell>
  </AuthGate>;
}
