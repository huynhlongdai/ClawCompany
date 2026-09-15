import {AuthGate} from "../../../components/AuthGate";import {V10AppShell} from "../../../components/V10AppShell";import {FounderCockpitV10} from "../../../components/FounderCockpitV10";
export default function Page(){return <AuthGate><V10AppShell title="Founder Cockpit" subtitle="Live company cognition, execution and governance"><FounderCockpitV10/></V10AppShell></AuthGate>}
