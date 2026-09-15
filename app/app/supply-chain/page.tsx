import {AuthGate} from "../../../components/AuthGate";
import {V13AppShell} from "../../../components/V13AppShell";
import {SupplyChainConsole} from "../../../components/SupplyChainConsole";
export default function Page(){return <AuthGate><V13AppShell title="Software Supply Chain" subtitle="SBOM, provenance and security gates for AI-generated code"><SupplyChainConsole/></V13AppShell></AuthGate>}
