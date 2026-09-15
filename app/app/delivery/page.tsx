import {V11AppShell} from "../../../components/V11AppShell";
import {RepositoryDeliveryConsole} from "../../../components/RepositoryDeliveryConsole";
export default function Page(){return <V11AppShell title="Delivery Pipeline" subtitle="Artifact bundle → worktree → tests → review → merge"><RepositoryDeliveryConsole/></V11AppShell>}
