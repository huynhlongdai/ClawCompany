import {AuthGate} from "../../components/AuthGate";
import {Onboarding} from "../../components/onboarding/Onboarding";
import {ToastProvider} from "../../components/ui/Toast";

export const metadata = {title: "Dựng công ty"};

/* Onboarding 4 bước (plan §5) — toàn màn, không có menu để người mới không bị 8 mục làm rối. */
export default function Page() {
  return <AuthGate><ToastProvider><Onboarding/></ToastProvider></AuthGate>;
}
