import {AuthGate} from "../../../components/AuthGate";
import {V17AppShell} from "../../../components/V17AppShell";
import {CustomersConsole} from "../../../components/CustomersConsole";
import {CreateButton} from "../../../components/CreateButton";

export default function Page() {
  return <AuthGate>
    <V17AppShell title="Khách hàng" subtitle="Khách hàng, ghế đã bán, đội phụ trách và chi phí AI thực tế"
                 action={<CreateButton/>}>
      <CustomersConsole/>
    </V17AppShell>
  </AuthGate>;
}
