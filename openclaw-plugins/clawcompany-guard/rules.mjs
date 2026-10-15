// M2e.2 luật cứng — lõi thuần (node --test). Bộ luật do ClawCompany biên dịch (runtime_rules.compile_all) và ghi vào
// plugins.entries.clawcompany-guard.config.rulesJson bằng config.patch. Cùng nguồn regex với phía Python.
export function parseRules(raw) {
  if (!raw) return { agents: {} };
  try {
    const d = typeof raw === "string" ? JSON.parse(raw) : raw;
    const agents = {};
    for (const [rid, a] of Object.entries(d?.agents || {})) {
      const rules = [];
      for (const r of a?.rules || []) {
        const res = [];
        for (const src of r.regex || []) {
          try { res.push(new RegExp(src, "iu")); } catch { /* luật hỏng bỏ qua, không làm sập plugin */ }
        }
        rules.push({ ...r, res, tools: r.tools || [] });
      }
      agents[rid] = { ...a, rules };
    }
    return { agents, replacement: d?.replacement || "[đã ẩn]" };
  } catch {
    return { agents: {} };
  }
}

export function agentOf(ctx, event) {
  if (ctx?.agentId) return String(ctx.agentId);
  const key = ctx?.sessionKey || event?.sessionKey || "";
  const m = /^agent:([^:]+):/.exec(String(key));
  return m ? m[1] : "";
}

export function isExternalSession(ctx) {
  const key = String(ctx?.sessionKey || "");
  if (/:a2a-|:portal/.test(key)) return true;
  const ch = String(ctx?.messageProvider || ctx?.channel || "");
  return !!ch && !["webchat", "gateway", "internal", "cli", ""].includes(ch);
}

export function checkText(seat, text, external) {
  const hits = [];
  for (const r of seat?.rules || []) {
    if (!["phrase", "regex", "pii"].includes(r.kind)) continue;
    if (r.external_only && !external) continue;
    for (const re of r.res) {
      const m = re.exec(text || "");
      if (m) { hits.push({ ruleId: r.id, action: r.action, match: m[0], message: r.message || r.name }); break; }
    }
  }
  return hits;
}

export function scrubText(seat, text, external, replacement = "[đã ẩn]") {
  let out = text || "";
  for (const r of seat?.rules || []) {
    if (r.action !== "scrub" || (r.external_only && !external)) continue;
    for (const re of r.res) out = out.replace(new RegExp(re.source, "giu"), replacement);
  }
  return out;
}

export function toolMatches(name, wanted) {
  const n = String(name || "").toLowerCase(), w = String(wanted || "").toLowerCase();
  return n === w || n.endsWith("__" + w) || n.endsWith("." + w) || n.endsWith("/" + w);
}

// block thắng approve; company_* ngoài danh sách công cụ của chức danh → block.
export function checkTool(seat, name) {
  let approve = null;
  for (const r of seat?.rules || []) {
    if (!["tool", "approval"].includes(r.kind)) continue;
    if (!r.tools.some((t) => toolMatches(name, t))) continue;
    if (r.kind === "tool") return { ruleId: r.id, action: "block", message: r.message || r.name };
    approve = approve || { ruleId: r.id, action: "approve", message: r.message || r.name };
  }
  if (approve) return approve;
  const allowed = seat?.allowedCompanyTools;
  if (Array.isArray(allowed)) {
    const m = /(?:^|__|[./])(company_[a-z0-9_]+)$/i.exec(String(name || ""));
    if (m && !allowed.includes(m[1].toLowerCase())) {
      return { ruleId: null, action: "block", message: `Chức danh không được dùng ${m[1]}` };
    }
  }
  return null;
}

export function reviseInstruction(hits) {
  const lines = [...new Set(hits.map((h) => `- ${h.message}`))].join("\n");
  return "Câu trả lời vừa rồi vi phạm luật cứng của công ty:\n" + lines +
    "\nViết lại câu trả lời tuân thủ đúng các luật trên (giữ nội dung hợp lệ, bỏ phần vi phạm). Không nhắc tới luật hay hệ thống kiểm tra.";
}

export function redact(text, limit = 300) {
  return String(text || "")
    .replace(/(?<![0-9])(?:\+84|84|0)(?:[ .]?[0-9]){9}(?![0-9])/g, "[đã ẩn]")
    .replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[đã ẩn]")
    .slice(0, limit);
}
