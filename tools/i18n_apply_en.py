"""Ghép bản dịch tiếng Anh vào messages/en.json.
Nguồn: các file JSON dạng {"ns": {"key": "en"}} hoặc {"chuỗi vi": "en"} (dịch theo nguyên văn, áp cho mọi namespace).
Khoá chưa có bản dịch giữ tiếng Việt và được liệt kê (để biết còn bao nhiêu)."""
import json, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
vi = json.load(open(os.path.join(ROOT, "messages/vi.json")))
enp = os.path.join(ROOT, "messages/en.json")
old = json.load(open(enp)) if os.path.exists(enp) else {}
by_key, by_text = {}, {}
for f in sys.argv[1:]:
    d = json.load(open(f))
    for k, v in d.items():
        if isinstance(v, dict): by_key.setdefault(k, {}).update(v)
        else: by_text[k] = v
en, missing = {}, []
for ns, kv in vi.items():
    en[ns] = {}
    for k, v in kv.items():
        if k in by_key.get(ns, {}): en[ns][k] = by_key[ns][k]
        elif v in by_text: en[ns][k] = by_text[v]
        elif v.strip() in by_text: en[ns][k] = v.replace(v.strip(), by_text[v.strip()])
        elif old.get(ns, {}).get(k) not in (None, v): en[ns][k] = old[ns][k]
        else: en[ns][k] = v; missing.append(f"{ns}.{k}\t{v}")
json.dump(en, open(enp, "w"), ensure_ascii=False, indent=1); open(enp, "a").write("\n")
print(f"{sum(len(x) for x in vi.values())} khoá, chưa dịch {len(missing)}")
open("/tmp/en_missing.tsv", "w").write("\n".join(missing))
