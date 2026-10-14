import {EmptyState} from "../components/ui/EmptyState";
import {ButtonLink} from "../components/ui/Button";

export default function NotFound() {
  return <EmptyState mood="ngu" title="Không có trang này" action={<ButtonLink href="/app/os" variant="primary">Về Tổng quan</ButtonLink>}>
    Đường dẫn có thể đã đổi. Dùng ô tìm kiếm (Ctrl K) để đi tới mọi trang, kể cả trang trong Phòng thí nghiệm.
  </EmptyState>;
}
