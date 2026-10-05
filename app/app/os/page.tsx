import {AuthGate} from "../../../components/AuthGate";
import {AppShell} from "../../../components/AppShell";
import {WorkspaceCockpit} from "../../../components/WorkspaceCockpit";
import {HomeRailIfHome} from "../../../components/HomeRailIfHome";
import {CreateButton} from "../../../components/CreateButton";

export default function Page() {
  return <AuthGate>
    <AppShell title="" subtitle="" action={<CreateButton/>} rail={<HomeRailIfHome/>}>
      <WorkspaceCockpit/>
    </AppShell>
  </AuthGate>;
}
