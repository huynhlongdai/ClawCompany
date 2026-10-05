"""Model giả có kịch bản cho phép thử approval đầu-cuối (D1.1).

Không phải model thật. Nó chỉ làm đúng một việc mà một model sẽ làm trong
phép thử: lượt đầu gọi tool ``exec`` với một lệnh cố định; khi đã thấy kết quả
tool thì trả câu trả lời cuối có trích kết quả. Mọi thứ còn lại — gateway
OpenClaw, tool exec, sổ duyệt, chặn lệnh, chạy lệnh — là thật.

API: OpenAI Chat Completions (``/v1/chat/completions``, có/không stream) và
``/v1/models``. Mọi request được ghi vào ``SCRIPTED_LLM_LOG`` (jsonl).
"""
import json, os, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SCRIPTED_LLM_PORT", "18800"))
LOG = os.environ.get("SCRIPTED_LLM_LOG", "/tmp/scripted_llm.jsonl")
COMMAND = os.environ.get("SCRIPTED_LLM_COMMAND",
                         "echo clawcompany-approval-e2e && date -u +%Y-%m-%dT%H:%M:%SZ")
MODEL = "approval-e2e"


def _log(kind, body):
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "body": body}, ensure_ascii=False) + "\n")


def _text(c):
    if isinstance(c, list):
        return " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return str(c or "")


def _tool_result(messages):
    """Kết quả tool gần nhất, nếu đã gọi tool rồi. Một lần gọi là đủ: sau đó
    luôn trả lời cuối, kể cả khi gateway chen tin nhắn ``user`` vào sau kết
    quả tool (đo được: OpenClaw thêm một lượt user sau mỗi kết quả)."""
    for m in reversed(messages):
        if m.get("role") == "tool":
            return _text(m.get("content"))
    return None


def _reply(messages):
    result = _tool_result(messages)
    if result is None:
        return {"tool_calls": [{"id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                                "function": {"name": "exec",
                                             "arguments": json.dumps({"command": COMMAND})}}]}
    return {"content": "Lệnh đã chạy. Kết quả: " + result.strip()[:400]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": "not found"})
        msgs = body.get("messages") or []
        reply = _reply(msgs)
        _log("request", {"roles": [m.get("role") for m in msgs], "tools": len(body.get("tools") or []),
                         "tail": [{"role": m.get("role"), "text": _text(m.get("content"))[:600]} for m in msgs[-3:]],
                         "stream": bool(body.get("stream")), "reply": reply})
        cid, now = "chatcmpl-" + uuid.uuid4().hex[:10], int(time.time())
        finish = "tool_calls" if "tool_calls" in reply else "stop"
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        if not body.get("stream"):
            msg = {"role": "assistant", "content": reply.get("content")}
            if "tool_calls" in reply:
                msg["tool_calls"] = reply["tool_calls"]
            return self._json(200, {"id": cid, "object": "chat.completion", "created": now, "model": MODEL,
                                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                                    "usage": usage})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def chunk(delta, fr=None, extra=None):
            c = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": MODEL,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": fr}]}
            if extra:
                c.update(extra)
            self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
            self.wfile.flush()

        chunk({"role": "assistant"})
        if "tool_calls" in reply:
            tc = reply["tool_calls"][0]
            chunk({"tool_calls": [{"index": 0, "id": tc["id"], "type": "function",
                                   "function": {"name": "exec", "arguments": tc["function"]["arguments"]}}]})
        else:
            chunk({"content": reply["content"]})
        chunk({}, finish)
        c = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": MODEL,
             "choices": [], "usage": usage}
        self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\ndata: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    print(f"scripted llm on :{PORT}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
