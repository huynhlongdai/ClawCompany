import test from "node:test";
import assert from "node:assert/strict";
import { leaks, scrub, termsFor, textOf } from "./guard.mjs";

const T = termsFor("cometapi/gpt-5-mini", "cometapi");
test("bắt tên model và nhà cung cấp", () => {
  assert.deepEqual(leaks("Em đang chạy trên GPT-5-mini của OpenAI qua CometAPI.", T).sort(),
                   ["cometapi", "gpt-5-mini", "openai"]);
  assert.ok(leaks("Mình dùng Claude Sonnet 5", T).length >= 2);
  assert.ok(leaks("model=cometapi/gpt-5-mini", T).length >= 1);
});
test("không bắt chữ thường", () => {
  assert.deepEqual(leaks("Dạ tiệm mở 8 giờ sáng đến 21 giờ, anh gửi ảnh qua Zalo giúp em nhé.", T), []);
  assert.deepEqual(leaks("Bình gốm men lam, giao trong 48 giờ, gửi bù miễn phí.", T), []);
  assert.deepEqual(leaks("Anh xem bản đồ Google Maps nhé", T), []);
});
test("che chữ", () => {
  assert.equal(scrub("Em là Claude.", T), "Em là hệ thống AI của công ty.");
});
test("đọc nội dung tin nhắn nhiều dạng", () => {
  assert.equal(textOf({ content: [{ type: "text", text: "a" }, { type: "text", text: "b" }] }), "a\nb");
  assert.equal(textOf("x"), "x");
});
