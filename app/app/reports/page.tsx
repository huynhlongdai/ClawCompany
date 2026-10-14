import {PageFrame} from "../../../components/shell/PageFrame";
import {ReportsConsole} from "../../../components/ReportsConsole";

export default function Page() {
  return 
    <PageFrame title="Báo cáo" subtitle="Chỉ số tổ chức có trị hiện tại, kỳ trước và mục tiêu — cùng các báo cáo đã sinh">
      <ReportsConsole/>
    </PageFrame>
  ;
}
