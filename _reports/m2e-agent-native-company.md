# M2e — Công ty agent-native (2026-10-16)

Spec: docs/m2e-agent-native-company.md. Migrations 0047–0050. Deployed on VM (company 3 Tiệm Gốm Mộc).

| Gói | Nội dung | Commit |
|---|---|---|
| M2e.1 | Phạm vi công ty: bỏ fallback "công ty đầu tiên" (422), company_id cho SOP + Inbox, tick bỏ công ty archived, KPI goal cùng công ty, i18n marketplace | 9383674 |
| M2e.2 | Luật cứng chạy runtime: company_rules/rule_violations, guard plugin 0.2.0 (before_agent_finalize rewrite, message_sending scrub/cancel, before_tool_call block/approval), MCP gateway enforce, tab "Luật cứng" | 3501c53, a039277, 5c7dc94 |
| M2e.3 | Hợp đồng dữ liệu vào/ra: io_contracts (JSON Schema), company_task_submit_output + company_process_step_outcome, sai chuẩn → làm lại, quá N lần → leo thang người; KPI output_conformance_rate | 809a634, eaec16f |
| M2e.4 | Thời gian 24/7: agent luôn trực, người có giờ làm/nghỉ phép/lễ; SLA theo bước/chức danh, beat sla.tick 60s, vi phạm → leo thang; ngoài giờ chuyển agent cùng chức danh hoặc xếp hàng; lưới phủ 7×24; KPI sla_attainment_rate | 0c22bc9, 21c2e6a, e03201e |
| M2e.5 | Nhân sự agent: tuân thủ luật, đúng chuẩn đầu ra, độ ổn định, SLA, giờ làm 24/7, chi phí/việc (USD) | 58d9b07 |

Tests: full backend suite pass (chạy theo lát, 92 file). tsc clean.

VM evidence: rule block/scrub/rewrite fired at gateway level (violations #2–#4 synthetic); contract reject/rework/escalate (inbox #30); SLA breach escalate (inbox #31, #33); after-hours reroute to CSKH agent; CSKH: rules 75%, outputs 33%, consistency 100%, $0.086/task; 11.4 h worked, 99% after office hours.

Cần chạy lại với agent thật sau khi nạp CometAPI + reset trần CSKH: guard hooks trong run thật, agent tự gọi submit_output, rework re-wake, SLA breach theo thời gian thật.

Open: /team/sla/tick chạy mọi công ty; coverage chưa trừ nghỉ phép; công ty 3 chưa có ghế người; ảnh career chụp nhầm công ty; demo process #5 instance #4/#5.
