import {AuthGate} from "../../../components/AuthGate";
import {V17AppShell} from "../../../components/V17AppShell";
import {WorkspaceCockpit} from "../../../components/WorkspaceCockpit";
import {HomeRail} from "../../../components/HomeRail";
import {CreateButton} from "../../../components/CreateButton";

export default function Page() {
  return <AuthGate>
    <V17AppShell
      title=""
      subtitle=""
      action={<CreateButton/>}
      rail={<HomeRail/>}
    >
      <WorkspaceCockpit/>
    </V17AppShell>
  </AuthGate>;
}
