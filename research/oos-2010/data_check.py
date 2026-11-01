"""回補資料健檢:每年交易日數、每天股票數(上市/上櫃)、法人有值比例、月營收每月家數、還原後單日漲跌超過 ±11% 的筆數。"""
import os, sys, json, gzip, collections
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
out = {"history": {}, "revenue": {}}
for y in sorted(os.listdir(os.path.join(ROOT, "history"))):
    if not y.isdigit(): continue
    fs = sorted(os.listdir(os.path.join(ROOT, "history", y)))
    n, flows, big, tx = [], 0, 0, 0
    for f in fs:
        d = json.load(gzip.open(os.path.join(ROOT, "history", y, f), "rt", encoding="utf-8"))
        n.append(len(d["s"])); tx += d.get("taiex") is not None
        flows += sum(1 for r in d["s"].values() if r[7] or r[8] or r[9])
        big += sum(1 for r in d["s"].values() if abs(r[5]) > 11)
    tot = sum(n) or 1
    out["history"][y] = {"交易日": len(fs), "每日股票數 最少/中位/最多": [min(n or [0]), sorted(n or [0])[len(n) // 2], max(n or [0])],
                         "法人有值比例%": round(flows / tot * 100, 1), "漲跌>11%筆數": big, "有加權指數的天數": tx}
for f in sorted(os.listdir(os.path.join(ROOT, "revenue"))):
    if f.endswith(".json") and f < "2019":
        out["revenue"][f[:7]] = len(json.load(open(os.path.join(ROOT, "revenue", f), encoding="utf-8")))
miss = [f"{y}-{m:02d}" for y in range(2010, 2019) for m in range(1, 13) if f"{y}-{m:02d}" not in out["revenue"]]
out["revenue_缺月"] = miss
print(json.dumps(out, ensure_ascii=False, indent=1))
