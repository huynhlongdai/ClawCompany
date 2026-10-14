import {PageFrame} from "../../../components/shell/PageFrame";
import {CustomersConsole} from "../../../components/CustomersConsole";
import {CreateButton} from "../../../components/CreateButton";

export default function Page() {
  return 
    <PageFrame title="Khách hàng" subtitle="Khách hàng, ghế đã bán, đội phụ trách và chi phí AI thực tế"
                 action={<CreateButton/>}>
      <CustomersConsole/>
    </PageFrame>
  ;
}
