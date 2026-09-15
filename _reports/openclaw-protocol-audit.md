# Đối chiếu tầng OpenClaw với upstream

> **Cập nhật 2026-09-15, sau khi sửa.** Báo cáo này ban đầu là suy luận từ
> schema. Sau đó đã dựng **OpenClaw 2026.9.4 thật** ở `localhost:18789` và đo:
> mọi dự đoán dưới đây đều đúng, cộng thêm một lỗi thứ năm mà chỉ chạy thật
> mới lộ ra (`chat.send` thiếu `idempotencyKey` và gửi `metadata` ngoài
> schema). **Cả năm đã được sửa và kiểm chứng lại** — xem mục "Kết quả sau khi
> sửa" ở cuối. Bằng chứng: `native-probe-before-fix.log`,
> `native-probe-after-fix.log`, `openclaw-gateway-boot.log`.

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

## Lỗi thứ năm — chỉ chạy thật mới lộ: `chat.send`

Suy luận từ schema không bắt được lỗi này vì nó nằm ở một schema khác
(`schema/logs-chat.ts`). Gateway thật trả về:

```
INVALID_REQUEST: invalid chat.send params:
  must have required property 'idempotencyKey';
  at root: unexpected property 'metadata'
```

```js
ChatSendParamsSchema  // đọc từ chính gateway đã cài
required: ["sessionKey", "message", "idempotencyKey"]
additionalProperties: false   // không có thuộc tính "metadata"
```

`run_agent` gửi `metadata` (chứa `company_task_id`, `label`) và không gửi
`idempotencyKey`. Đây là **đường gửi việc chính của cả sản phẩm** — mỗi lần
ClawCompany dispatch một task cho agent đều đi qua đây.

Đã sửa: metadata ở lại phía ClawCompany; `idempotencyKey` khoá theo task
(`clawcompany:<session-key>:task-<id>`) để retry transport không sinh hai lượt
chạy, chỉ rơi về uuid khi không có task id.

---

## Kết quả sau khi sửa (đo với gateway thật)

| Phép thử | Trước | Sau |
| --- | --- | --- |
| `health()` | 1008 policy violation | `healthy`, `runtimeVersion 2026.9.4` |
| handshake | kết nối bị đóng | `hello-ok`, protocol 4, role `operator`, scopes `[operator.read, operator.write]` |
| `sessions.create` | không tới được | `ok: true` + `sessionId` thật |
| `sessions.list` | không tới được | thấy session vừa tạo |
| `list_agents()` | không tới được | nhận ra agent `dev` |
| `subscribe {"key"}` | — | `ok: true` |
| `subscribe {"sessionKey"}` (bản cũ) | — | `ok: false`, `INVALID_REQUEST: must have required property 'key'` |
| `chat.send` | `INVALID_REQUEST` | đi qua tầng giao thức, dừng ở `no authentication source configured for openai` |

Lời dừng cuối cùng là **cấu hình model**, không phải giao thức: gateway dev
không có credential OpenAI. Nghĩa là hợp đồng đã đúng tới tận tầng chạy model.

Vẫn chưa kiểm chứng: một lượt chạy hoàn chỉnh tới `terminal state`, và luồng
approval thật (cần một lệnh bị gate bởi exec approval).

---

## Việc đã làm và việc còn lại

**Đã làm** (commit `26e5a4d`), theo đúng thứ tự này vì frame sai chặn ở bước
đầu tiên nên sửa lẻ không kiểm chứng được gì:

1. Viết lại `_connect_frame()` theo `ConnectParamsSchema`, bọc trong request
   frame với `method: "connect"`.
2. Thêm `"type": "req"` vào `_rpc` và `stream_run`.
3. Đọc `ok` + `payload` thay cho `result`; coi `ok is False` là lỗi.
4. Đổi tham số subscribe thành `{"key": ...}`; giữ `sessionKey` cho
   `chat.send` và pin cả hai bằng test.
5. Thêm một lớp test đối chiếu hình dạng frame với schema upstream đã dẫn ở
   trên, để lần sau upstream đổi thì test đỏ chứ không phải người dùng phát
   hiện.
6. Thêm `chat.send`: `idempotencyKey` bắt buộc, bỏ `metadata`.

**Còn lại cho v36:**

- Chạy trọn một task tới trạng thái kết thúc, với một gateway có credential
  model, và xác nhận `runtime_stream` ghi đúng các event.
- Kiểm chứng luồng approval thật: cần một lệnh bị `exec approval` gate để thấy
  `exec.approval.list` / `resolve` hoạt động đầu-cuối.
- Cân nhắc dùng `reviewer` và `grantExpiresInDays` — hai field upstream có mà
  ClawCompany đang bỏ trống.
- Một lượt chạy hoàn chỉnh vẫn cần `sessions.create` với `idempotencyKey`
  (schema có, hiện chưa dùng).

**Cảnh báo về cách đo**: 89 test của v19→v35 đều xanh với cả năm lỗi trên, vì
chúng kiểm *nội dung params* bằng double và grep source, không kiểm *hình dạng
frame* gửi lên dây. Một test suite xanh ở đây không phải bằng chứng về khả
năng kết nối. `tests/test_v35_1_protocol_frames.py` (16 test) đóng đúng khoảng
trống đó, và cố tình **không** cần gateway — một test cần gateway sẽ bị bỏ qua
trong CI và lỗi quay lại.
