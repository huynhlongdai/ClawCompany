import {AuthGate} from "../../../components/AuthGate";import {V10AppShell} from "../../../components/V10AppShell";import {QualitySLAConsole} from "../../../components/QualitySLAConsole";
export default function Page(){return <AuthGate><V10AppShell title="QA & SLA" subtitle="Evaluator gates, deadlines and automatic escalation"><QualitySLAConsole/></V10AppShell></AuthGate>}
