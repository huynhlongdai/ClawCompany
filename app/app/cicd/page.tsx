import {AuthGate} from "../../../components/AuthGate";
import {V13AppShell} from "../../../components/V13AppShell";
import {CICDGraphConsole} from "../../../components/CICDGraphConsole";
export default function Page(){return <AuthGate><V13AppShell title="CI/CD Graph" subtitle="Auditable DAG execution from commit to immutable release"><CICDGraphConsole/></V13AppShell></AuthGate>}
