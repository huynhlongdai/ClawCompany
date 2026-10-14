"use client";
import {useCallback, useEffect, useState} from "react";
import {apiV12} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill} from "./ui/StatusPill";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {useToast} from "./ui/Toast";

/* Cài đặt › Bí mật (v12): ClawCompany chỉ lưu THAM CHIẾU tới bí mật (env:, vault:…) và
   quyền dùng gắn với danh tính. Giá trị chỉ được giải lúc chạy và gắn vào sandbox
   dưới dạng tệp tạm — không vào DB, không vào prompt. Form không có ô nhập giá trị. */
type Row = Record<string, any>;
const CLASS_VI: Record<string, string> = {restricted: "Hạn chế", confidential: "Mật", internal: "Nội bộ", public: "Công khai"};

export function SecretsConsole() {
  const toast = useToast();
  const [items, setItems] = useState<Row[] | null>(null), [grants, setGrants] = useState<Row[]>([]), [err, setErr] = useState<unknown>(null);
  const [name, setName] = useState(""), [ref, setRef] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [s, g] = await Promise.allSettled([apiV12.secrets(), apiV12.secretGrants()]);
    if (s.status === "fulfilled") setItems((s.value as Row[]) || []); else { setErr(s.reason); setItems([]); }
    if (g.status === "fulfilled") setGrants((g.value as Row[]) || []);
  }, []);
  useEffect(() => { load(); }, [load]);
  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await apiV12.createSecret({organization_id: activeOrganizationId(), name, provider: ref.split(":")[0] || "env", external_ref: ref, classification: "restricted"});
      toast(`Đã đăng ký tham chiếu “${name}”`); setName(""); setRef(""); await load(); }
    catch (e2) { setErr(e2); } finally { setBusy(false); }
  }
  return <div className="ui-grid" style={{gap: 16}}>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} context="Bí mật"/> : null}
    <div className="ui-grid is-2">
      <Panel title="Đăng ký tham chiếu bí mật" desc="Không có ô nhập giá trị — chỉ lưu nơi bí mật nằm">
        <form className="ui-form" onSubmit={create}>
          <FormRow>
            <Field label="Tên"><input value={name} onChange={e => setName(e.target.value)} placeholder="VD: Token triển khai…" autoComplete="off"/></Field>
            <Field label="Tham chiếu" hint="dạng nguồn:tên, VD env:DEPLOY_TOKEN"><input value={ref} onChange={e => setRef(e.target.value)} placeholder="env:DEPLOY_TOKEN…" spellCheck={false} autoComplete="off"/></Field>
          </FormRow>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !ref.includes(":")}>Đăng ký</Button>
        </form>
      </Panel>
      <Panel title="Nguyên tắc">
        <dl className="ui-kv">
          <dt>Lưu giá trị trong DB</dt><dd>Không bao giờ</dd>
          <dt>Đưa vào prompt agent</dt><dd>Không bao giờ</dd>
          <dt>Lúc chạy</dt><dd>Gắn vào sandbox dưới dạng tệp tạm <code translate="no">/run/secrets/*</code></dd>
          <dt>Ai được dùng</dt><dd>Chỉ danh tính có quyền (người, agent, hồ sơ sandbox, môi trường)</dd>
        </dl>
      </Panel>
    </div>
    <Panel title="Tham chiếu đã đăng ký" desc="Chỉ thấy thông tin mô tả" flush>
      {items && items.length === 0 ? <EmptyState compact mood="ngu" title="Chưa có bí mật nào">Đăng ký tham chiếu đầu tiên ở form bên trên.</EmptyState>
        : <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>Tên</th><th>Nguồn</th><th>Tham chiếu</th><th>Mức</th></tr></thead>
          <tbody>{(items || []).map(x => <tr key={x.id}><td>{x.name}</td><td>{x.provider}</td><td><code translate="no">{x.external_ref}</code></td>
            <td><StatusPill tone="wait">{CLASS_VI[x.classification] || x.classification}</StatusPill></td></tr>)}</tbody></table></div>}
    </Panel>
    <Panel title="Quyền dùng đang có" desc="Gắn với người, agent, hồ sơ sandbox hoặc môi trường triển khai" flush>
      {grants.length === 0 ? <p className="ui-empty-line" style={{padding: "12px 16px"}}>Chưa cấp quyền nào.</p>
        : <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>Quyền</th><th>Bí mật</th><th>Người</th><th>Agent</th><th>Sandbox</th><th>Trạng thái</th></tr></thead>
          <tbody>{grants.map(x => <tr key={x.id}><td>#{x.id}</td><td>#{x.secret_reference_id}</td><td>{x.member_id ? `#${x.member_id}` : "—"}</td><td>{x.agent_id ? `#${x.agent_id}` : "—"}</td>
            <td>{x.sandbox_profile_id ? `#${x.sandbox_profile_id}` : "—"}</td><td><StatusPill tone={x.is_active ? "ok" : "neutral"}>{x.is_active ? "Đang hiệu lực" : "Đã tắt"}</StatusPill></td></tr>)}</tbody></table></div>}
    </Panel>
  </div>;
}
