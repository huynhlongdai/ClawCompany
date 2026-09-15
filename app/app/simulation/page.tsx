import {AuthGate} from "../../../components/AuthGate";import {V10AppShell} from "../../../components/V10AppShell";import {DigitalTwinConsole} from "../../../components/DigitalTwinConsole";
export default function Page(){return <AuthGate><V10AppShell title="Digital Twin" subtitle="What-if simulation before changing the real AI company"><DigitalTwinConsole/></V10AppShell></AuthGate>}
