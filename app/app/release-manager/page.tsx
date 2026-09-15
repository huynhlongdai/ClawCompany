import {AuthGate} from "../../../components/AuthGate";
import {V13AppShell} from "../../../components/V13AppShell";
import {ReleaseManagerV13Console} from "../../../components/ReleaseManagerV13Console";
export default function Page(){return <AuthGate><V13AppShell title="Release Manager" subtitle="Governed promotion, progressive delivery and health-based rollback"><ReleaseManagerV13Console/></V13AppShell></AuthGate>}
