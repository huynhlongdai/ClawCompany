import {AuthGate} from "../../../components/AuthGate";import {V10AppShell} from "../../../components/V10AppShell";import {EventAutomationConsole} from "../../../components/EventAutomationConsole";
export default function Page(){return <AuthGate><V10AppShell title="Company Events" subtitle="Durable event bus and trigger automation"><EventAutomationConsole/></V10AppShell></AuthGate>}
