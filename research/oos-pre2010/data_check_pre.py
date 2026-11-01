"""2004–2009 回補健檢。依 PROTOCOL.md:只輸出筆數、比率、欄位名稱,不輸出任何價格、報酬或指數點位。"""
import os, sys, json, gzip, re, html, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
out = {"history": {}, "revenue": {}}
for y in [str(x) for x in range(2004, 2011)]:
    p = os.path.join(ROOT, "history", y)
    if not os.path.isdir(p): out["history"][y] = "missing"; continue
    fs = sorted(os.listdir(p)); n, tx, otc_days, big = [], 0, 0, 0
    for f in fs:
        d = json.load(gzip.open(os.path.join(p, f), "rt", encoding="utf-8"))
        n.append(len(d["s"])); tx += d.get("taiex") is not None
        big += sum(1 for r in d["s"].values() if abs(r[5]) > 11)
    out["history"][y] = {"交易日": len(fs), "每日股票數 最少/中位/最多": [min(n or [0]), sorted(n or [0])[len(n) // 2], max(n or [0])],
                         "有加權指數的天數": tx, "漲跌>11%筆數": big, "第一天": fs[0][:10] if fs else None}
rv = {}
for f in sorted(os.listdir(os.path.join(ROOT, "revenue"))):
    if f.endswith(".json") and f < "2011":
        rv[f[:7]] = json.load(open(os.path.join(ROOT, "revenue", f), encoding="utf-8"))
out["revenue"] = {k: len(v) for k, v in rv.items()}
out["revenue_缺月"] = [f"{y}-{m:02d}" for y in range(2004, 2010) for m in range(1, 13) if f"{y}-{m:02d}" not in rv]
# 欄位檢查(不看數值):公告的年增率 vs 用 12 個月前營收自己算的年增率,差 < 1 個百分點的比例
ok = tot = 0
for k, v in rv.items():
    y, m = int(k[:4]), int(k[5:]); k0 = "%04d-%02d" % (y - 1, m)
    if k0 not in rv: continue
    for c, (r, yoy, mom) in v.items():
        r0 = rv[k0].get(c, [None])[0]
        if yoy is None or not r0: continue
        tot += 1; ok += abs((r / r0 - 1) * 100 - yoy) < 1
out["年增率欄位吻合%"] = round(ok / tot * 100, 1) if tot else None
print(json.dumps(out, ensure_ascii=False, indent=1))
