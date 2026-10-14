import {PageFrame} from "../../../components/shell/PageFrame";
import {CustomersConsole} from "../../../components/CustomersConsole";
import {CreateButton} from "../../../components/CreateButton";

export default function Page() {
  return (
    <PageFrame
                 action={<CreateButton/>}>
      <CustomersConsole/>
    </PageFrame>
  );
}
