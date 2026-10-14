import {PageFrame} from "../../../components/shell/PageFrame";
import {RepositoryDeliveryConsole} from "../../../components/RepositoryDeliveryConsole";
export default function Page(){return <PageFrame title="Delivery Pipeline" subtitle="Artifact bundle → worktree → tests → review → merge"><RepositoryDeliveryConsole/></PageFrame>}
