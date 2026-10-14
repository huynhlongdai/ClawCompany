"use client";
import Link from "next/link";
import {useEffect, useState} from "react";
import {Icon} from "../Icon";
import {Panel} from "../ui/Panel";
import {Segmented} from "../ui/Tabs";
import {StatusPill} from "../ui/StatusPill";
import {ButtonLink} from "../ui/Button";
import {useCounts} from "../shell/Shell";
import {getOrg} from "../../lib/counts";
import {apiV19} from "../../lib/api";
import {ThemePref, useCompanyId, useLab, useThemePref} from "../../lib/prefs";
import {LAB_PAGES} from "../../lib/nav";

const SHORTCUTS: [string, string][] = [["Ctrl K / ⌘K", "Tìm và đi tới mọi trang, việc, agent"], ["C", "Tạo việc (trong Công việc)"], ["/", "Tìm việc"],
  ["J · K", "Chọn việc trên/dưới"], ["Enter", "Mở side-peek"], ["Esc", "Đóng side-peek, hộp thoại"]];

export function SettingsHome() {
  useCounts();
  const org = getOrg();
  const [theme, setTheme] = useThemePref();
  const [lab] = useLab();
  const [companyId, setCompanyId] = useCompanyId();
  const [health, setHealth] = useState<any>(null), [hErr, setHErr] = useState(false);
  useEffect(() => { apiV19.health().then(setHealth).catch(() => setHErr(true)); }, []);
  const status = health?.health?.status;
  return <div className="ui-grid is-2">
    <Panel title="Kết nối OpenClaw" desc="Gateway chạy agent của công ty" actions={<ButtonLink href="/app/openclaw" size="sm">Mở kiểm tra</ButtonLink>}>
      <div className="set-line">
        {hErr ? <StatusPill tone="risk">Không đọc được trạng thái</StatusPill>
          : !health ? <StatusPill tone="neutral">Đang kiểm tra…</StatusPill>
          : <StatusPill tone={status === "healthy" ? "ok" : "wait"}>{status === "healthy" ? "Đang kết nối" : `Chưa sẵn sàng (${status || "không rõ"})`}</StatusPill>}
        <span className="ui-row-meta">{health?.runtime?.mode ? `Chế độ ${health.runtime.mode}` : "Chạy “Kiểm tra lại” ở trang OpenClaw để xem từng bước."}</span>
      </div>
    </Panel>
    <Panel title="Giao diện" desc="Lưu trên trình duyệt này">
      <Segmented<ThemePref> label="Giao diện" value={theme} onChange={setTheme}
        options={[{value: "light", label: "Sáng"}, {value: "dark", label: "Tối"}, {value: "system", label: "Theo máy"}]}/>
    </Panel>
    <Panel title="Công ty" desc={org.name ? `Tổ chức ${org.name}` : "Đang tải…"} flush actions={<ButtonLink href="/onboarding" size="sm" icon="plus">Tạo công ty</ButtonLink>}>
      <div className="ui-list">
        {org.companies.map(c => <button key={c.id} className="ui-row" onClick={() => setCompanyId(c.id)} aria-pressed={c.id === (companyId ?? org.companies[0]?.id)}>
          <Icon name="building" size={16}/><span className="ui-row-main"><span className="ui-row-title">{c.name}</span><span className="ui-row-meta">{c.industry || "—"}</span></span>
          {c.id === (companyId ?? org.companies[0]?.id) && <StatusPill tone="ok">Đang xem</StatusPill>}
        </button>)}
        {!org.companies.length && <p className="ui-row ui-row-meta">Chưa có công ty nào — bấm Tạo công ty.</p>}
      </div>
    </Panel>
    <Panel title="Phòng thí nghiệm" desc={`${LAB_PAGES.length} trang ít dùng (giao phần mềm, SRE, điều hành đời cũ)`}
      actions={<ButtonLink href="/app/settings/lab" size="sm">{lab ? "Đang bật" : "Đang tắt"} · Quản lý</ButtonLink>}>
      <p className="ui-row-meta" style={{whiteSpace: "normal"}}>Ẩn khỏi menu và tìm kiếm để màn hình gọn. Đường dẫn cũ vẫn mở được.</p>
    </Panel>
    <Panel title="Phím tắt" flush>
      <div className="ui-list">{SHORTCUTS.map(([k, d]) => <div key={k} className="ui-row"><kbd>{k}</kbd><span className="ui-row-meta" style={{whiteSpace: "normal"}}>{d}</span></div>)}</div>
    </Panel>
    <Panel title="Kỹ năng, bí mật, thành viên" flush>
      <div className="ui-list">
        <Link className="ui-row" href="/app/agent-tools"><Icon name="shield" size={16}/><span className="ui-row-main"><span className="ui-row-title">Kỹ năng & công cụ</span><span className="ui-row-meta">Công cụ agent được gọi, quyền theo ghế</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/secrets"><Icon name="key" size={16}/><span className="ui-row-main"><span className="ui-row-title">Bí mật</span><span className="ui-row-meta">Tham chiếu khoá, cấp quyền dùng — không lưu giá trị</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/team?tab=people&from=settings"><Icon name="users" size={16}/><span className="ui-row-main"><span className="ui-row-title">Thành viên</span><span className="ui-row-meta">Mời người, đổi vai, thu hồi quyền</span></span><Icon name="chevron-right" size={14}/></Link>
      </div>
    </Panel>
  </div>;
}
