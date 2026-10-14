"""Thêm khoá vào cả hai catalog: python3 tools/i18n_add.py ns.key "vi" "en" [ns.key "vi" "en" ...]"""
import json, sys
a = sys.argv[1:]
cats = {f: json.load(open(f)) for f in ("messages/vi.json", "messages/en.json")}
for i in range(0, len(a), 3):
    ns, k = a[i].split(".", 1)
    cats["messages/vi.json"].setdefault(ns, {})[k] = a[i + 1]
    cats["messages/en.json"].setdefault(ns, {})[k] = a[i + 2]
for f, d in cats.items():
    json.dump(d, open(f, "w"), ensure_ascii=False, indent=1); open(f, "a").write("\n")
