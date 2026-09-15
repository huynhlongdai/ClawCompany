import {AuthGate} from "../../../components/AuthGate";
import {V13AppShell} from "../../../components/V13AppShell";
import {WorkspaceGatewayV13Console} from "../../../components/WorkspaceGatewayV13Console";
export default function Page(){return <AuthGate><V13AppShell title="Workspace Gateway" subtitle="Provider-neutral file exchange and artifact handoff"><WorkspaceGatewayV13Console/></V13AppShell></AuthGate>}
