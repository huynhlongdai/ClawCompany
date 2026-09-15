# Đối chiếu tầng OpenClaw với upstream (kiểm chứng bằng source, không bằng suy đoán)

Ngày: 2026-09-15. Đối chiếu `backend/app/runtime/openclaw_native.py` +
`openclaw_protocol.py` với repo upstream `openclaw/openclaw`
(commit `c0be265`, nhánh mặc định) và `docs.openclaw.ai`.

Nguồn đã đọc trực tiếp:

- `packages/gateway-protocol/src/schema/frames.ts`
- `packages/gateway-protocol/src/schema/exec-approvals.ts`
- `src/gateway/methods/core-descriptors.ts`
- `src/gateway/server-methods/exec-approval.ts`
- `src/gateway/server-methods/sessions-subscriptions.ts`
- `docs/gateway/clients.md`, `docs/gateway/protocol/rpc-session-control.md`

---

## Kết luận

**OpenClaw là thật, và `openclaw_protocol.py` mô tả nó khá đúng ở tầng khái
niệm** — cổng 18789, handshake khai `role` + `scopes`, không có
`agents.create`/`agents.run`, công việc chạy qua `sessions.create` +
`chat.send`, session key `agent:<id>:main`, `POST /tools/invoke` là toàn quyền
operator. Những điều đó khớp upstream.

**Nhưng ở tầng khung truyền (wire format), adapter native không thể hoạt động
với một gateway thật.** Không phải một endpoint sai — là *mọi* frame đều sai.
Đây là lý do vì sao `OPENCLAW_MODE=native` chưa từng chạy được, và vì sao toàn
bộ v19→v35 chỉ chạy ở `mock`.

Mức nghiêm trọng: **chặn toàn bộ**. Sản phẩm tự định vị là "xây trên nền cốt
lõi openclaw", nên đây là lỗi duy nhất phủ định mệnh đề đó.

---

## 1. Frame request thiếu `type: "req"` — chặn mọi RPC

Upstream, `frames.ts`:

```ts
export const RequestFrameSchema = closedObject({
  type: Type.Literal("req"),
  id: NonEmptyString,
  method: NonEmptyString,
  params: Type.Optional(Type.Unknown()),
  traceparent: ..., expectedProfileId: ...,
});
```

`closedObject` = `additionalProperties: false`, và `type` là **literal bắt
buộc**.

ClawCompany, `openclaw_native.py::_rpc`:

```python
await ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
```

Không có `type`. Frame bị từ chối ở tầng validate envelope, trước khi tới
handler. **Mọi** lời gọi RPC: status, sessions.create, chat.send, abort,
approval resolve/list, history.

## 2. Đọc response sai khoá — kể cả nếu frame được chấp nhận

Upstream:

```ts
export const ResponseFrameSchema = closedObject({
  type: Type.Literal("res"),
  id: NonEmptyString,
  ok: Type.Boolean(),
  payload: Type.Optional(Type.Unknown()),
  error: Type.Optional(ErrorShapeSchema),
});
```

Kết quả nằm ở **`payload`**, kèm cờ **`ok`**. ClawCompany đọc `msg.get("result")`
(`_rpc`, dòng 96). Với gateway thật, `result` luôn là `None`, nên `run_agent`
sẽ luôn trả `run_id = ""`, `status = "running"` — một trạng thái bịa.

Cũng vậy: `_rpc` kiểm `msg.get("error")` nhưng không kiểm `ok is False`. Một
lỗi có `ok: false` mà không kèm `error` sẽ bị đọc thành thành công.

## 3. Handshake sai hình dạng hoàn toàn

Upstream: `connect` là một **method trong request frame**, params theo
`ConnectParamsSchema` (closedObject):

```json
{"type":"req","id":"…","method":"connect","params":{
  "minProtocol":4,"maxProtocol":4,
  "client":{"id":"cli","version":"1.2.3","platform":"macos","mode":"operator"},
  "role":"operator","scopes":["operator.read","operator.write"],
  "auth":{"token":"…"}
}}
```

ClawCompany gửi một frame `{"type": "connect", ...}` phẳng với
`protocolVersion`, `client: {name, version}` và `token` ở cấp cao nhất. Trong
`ConnectParamsSchema`:

- `client` yêu cầu `id`, `version`, `platform`, `mode` — **không có `name`**;
- phiên bản giao thức khai qua `minProtocol`/`maxProtocol`, không phải
  `protocolVersion`;
- token nằm trong `auth.token`, không nằm ở cấp cao nhất.

Upstream đóng kết nối với code **1008 (policy violation)** nếu frame đầu tiên
không phải `connect` hợp lệ.

Ghi chú: `Authorization: Bearer` ở header HTTP upgrade (`_headers()`) không
thay cho `auth.token` trong frame.

## 4. `sessions.messages.subscribe` sai tên tham số

Upstream dùng `{ key: <sessionKey> }` — thấy nhất quán ở
`src/gateway/session-message-events.test.ts`, `packages/gateway-client`,
client Android/Swift, và bench script. ClawCompany gửi
`{"sessionKey": session_key}` (`stream_run`, dòng 184). Schema đóng ⇒ đăng ký
stream bị từ chối ⇒ `/app/live-runs` và toàn bộ v20→v26 (follower, lease,
takeover, reconcile) không bao giờ nhận được event nào từ gateway thật.

Nghịch lý đáng ghi: `chat.send` **đúng là** dùng `sessionKey`. Upstream không
nhất quán giữa hai method, nên đây là chỗ dễ sai và cần pin bằng test.

## 5. `exec.approval.resolve` gửi field ngoài schema — ĐÃ SỬA

```ts
ExecApprovalResolveParamsSchema = closedObject({
  id, decision, reviewer?, grantExpiresInDays?
})
```

v23 gửi kèm `sessionKey` "như một disambiguator" ⇒ bị từ chối
`INVALID_REQUEST`. Đã bỏ trong commit `657262a`, kèm test pin tập khoá đúng
bằng `{id, decision}`.

Hai điều v23 kết luận sai theo hướng bảo thủ, nay biết rõ:

- **`reviewer` tồn tại** (`ApprovalChannelReviewerSchema`). v23 nói "gateway
  không có chỗ cho ghi chú người duyệt" — đúng là không có field *reason*,
  nhưng danh tính người duyệt thì gửi được. Đây là cơ hội cho v36.
- **`grantExpiresInDays` tồn tại** cho `allow-always`. ClawCompany hiện không
  dùng, nên một standing grant được cấp qua ClawCompany là vô hạn đến khi bị
  thu hồi tay.
- `kind: "exec"` là của method hợp nhất `approvals.resolve`, **không** phải của
  `exec.approval.resolve`. Thêm vào sẽ vi phạm schema theo chiều ngược lại.

## 6. `exec.approval.list` không có bộ lọc — ĐÃ SỬA

Handler upstream là `async ({ respond, client, context })`: không nhận params.
Bộ lọc `sessionKey` mà v24 suy đoán không tồn tại. Đã bỏ; việc lọc phải làm
phía ClawCompany sau khi nhận danh sách.

## 7. Danh sách scope thiếu, không nguy hiểm

`OPERATOR_SCOPES` trong `openclaw_protocol.py` thiếu `operator.questions` và
`operator.talk`. ClawCompany không yêu cầu hai scope này nên không ảnh hưởng,
nhưng hằng số đang tự nhận là "tập đóng" thì nên đúng.

---

## Việc cần làm (đề xuất v36, chưa thực hiện)

Nhóm 1–4 là một khối: sửa lẻ không kiểm chứng được gì, vì frame sai chặn ở
bước đầu tiên.

1. Viết lại `_connect_frame()` theo `ConnectParamsSchema`, bọc trong request
   frame với `method: "connect"`.
2. Thêm `"type": "req"` vào `_rpc` và `stream_run`.
3. Đọc `ok` + `payload` thay cho `result`; coi `ok is False` là lỗi.
4. Đổi tham số subscribe thành `{"key": ...}`; giữ `sessionKey` cho
   `chat.send` và pin cả hai bằng test.
5. Thêm một lớp test đối chiếu hình dạng frame với schema upstream đã dẫn ở
   trên, để lần sau upstream đổi thì test đỏ chứ không phải người dùng phát
   hiện.
6. Chỉ sau đó mới nói được câu "ClawCompany nói được giao thức OpenClaw" —
   và vẫn cần một gateway thật để đóng dấu.

**Cảnh báo về cách đo**: 89 test hiện tại của v19→v35 đều xanh với các lỗi
trên, vì chúng kiểm *nội dung params* bằng double và grep source, không kiểm
*hình dạng frame* gửi lên dây. Một test suite xanh ở đây không phải bằng chứng
về khả năng kết nối.
