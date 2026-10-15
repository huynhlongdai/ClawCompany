import test from "node:test";
import assert from "node:assert/strict";
import { agentOf, checkText, checkTool, isExternalSession, parseRules, redact, scrubText } from "./rules.mjs";

// Chuỗi JSON đúng dạng runtime_rules.compile_all sinh ra (regex do Python biên dịch).
const RAW = JSON.stringify({ v: 1, replacement: "[đã ẩn]", agents: { "gom-cskh": { seat: 9, company: 3, allowedCompanyTools: ["company_context", "company_knowledge_search"], rules: [
  { id: 1, kind: "regex", action: "revise", message: "Không hứa hoàn tiền 100%", external_only: false,
    regex: ["(cam kết|hứa|chắc chắn)\\s+(sẽ\\s+)?hoàn\\s+(tiền\\s+)?(100|toàn bộ)"], tools: [] },
  { id: 2, kind: "pii", action: "scrub", message: "Không đưa dữ liệu cá nhân ra ngoài", external_only: true,
    regex: ["(?<![0-9])(?:\\+84|84|0)(?:[ .]?[0-9]){9}(?![0-9])", "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"], tools: [] },
  { id: 3, kind: "phrase", action: "block", message: "Không chê đối thủ", external_only: false,
    regex: ["gốm\\s+Bát\\s+Tràng\\s+dỏm"], tools: [] },
  { id: 4, kind: "tool", action: "block", message: "Không xoá dữ liệu", regex: [], tools: ["company_memory_forget"] },
  { id: 5, kind: "approval", action: "approve", message: "Gửi agent ngoài cần duyệt", regex: [], tools: ["company_delegate_external"] },
] } } });
const R = parseRules(RAW);
const S = R.agents["gom-cskh"];

test("tìm seat từ ctx.agentId hoặc sessionKey", () => {
  assert.equal(agentOf({ agentId: "gom-cskh" }), "gom-cskh");
  assert.equal(agentOf({ sessionKey: "agent:gom-cskh:task-12" }), "gom-cskh");
  assert.equal(agentOf({}), "");
});
test("luật chữ: revise khi hứa hoàn 100%, không bắt câu đúng chính sách", () => {
  const h = checkText(S, "Dạ em cam kết hoàn tiền 100% cho anh ạ", false);
  assert.deepEqual(h.map((x) => [x.ruleId, x.action]), [[1, "revise"]]);
  assert.deepEqual(checkText(S, "Dạ em sẽ báo quản lý duyệt hoàn tiền theo chính sách đổi trả 7 ngày", false), []);
});
test("dữ liệu cá nhân chỉ áp khi ra ngoài; che chữ", () => {
  const t = "Khách Lan sđt 0912 345 678, email lan@gmail.com";
  assert.deepEqual(checkText(S, t, false), []);
  assert.deepEqual(checkText(S, t, true).map((x) => x.ruleId), [2]);
  assert.equal(scrubText(S, t, true), "Khách Lan sđt [đã ẩn], email [đã ẩn]");
});
test("cụm từ cấm block", () => {
  assert.equal(checkText(S, "hàng gốm Bát  Tràng dỏm lắm", true)[0].action, "block");
});
test("tool: cấm, cần duyệt, ngoài danh sách chức danh; tiền tố server MCP", () => {
  assert.equal(checkTool(S, "clawcompany__company_memory_forget").action, "block");
  assert.equal(checkTool(S, "company_delegate_external").action, "approve");
  assert.equal(checkTool(S, "clawcompany__company_budget_check").action, "block");     // không có trong allowedCompanyTools
  assert.equal(checkTool(S, "clawcompany__company_knowledge_search"), null);
  assert.equal(checkTool(S, "read"), null);
});
test("phiên ngoài", () => {
  assert.equal(isExternalSession({ sessionKey: "agent:gom-cskh:a2a-abc" }), true);
  assert.equal(isExternalSession({ sessionKey: "agent:gom-cskh:task-1" }), false);
  assert.equal(isExternalSession({ messageProvider: "telegram" }), true);
});
test("JSON hỏng hoặc regex hỏng không làm sập plugin", () => {
  assert.deepEqual(parseRules("{oops").agents, {});
  const bad = parseRules(JSON.stringify({ agents: { a: { rules: [{ id: 1, kind: "regex", action: "revise", regex: ["(unclosed"] }] } } }));
  assert.deepEqual(checkText(bad.agents.a, "(unclosed", false), []);
});
test("che PII trong trích đoạn báo về", () => {
  assert.equal(redact("gọi 0912345678 nhé"), "gọi [đã ẩn] nhé");
});
