"""地雷股條件回測(研究用,不在每日排程裡跑)。樣本來自 explosion_study.py(先跑它),財報來自 quality.py。

問題:財報狗式的地雷條件(本業虧損、獲利靠業外、負債比偏高、流動比率 < 100%、淨值跌破面額、累積虧損),
在我們的評級裡,是否真的讓之後的表現變差、大跌機率變高?只有回測證明有用的,才會在健檢裡標成「有回測依據」。
每個營收公告日只用當時已過申報期限的最新一季(margin.available)。

用法:python scripts/landmine_test.py > 報告.txt   (另寫 data/radar/landmine.json)
"""
import json
import os
import sys

import pandas as pd

import history
import margin
import quality
import signals as S

# 樣本是 explosion_study.py 在本機產生的暫存檔,不是外部資料
R = pd.read_pickle(os.path.join(os.environ.get("TEMP", "/tmp"), "mr_samples.pkl"))
SPLIT = "2023-01-01"
pl, bs = quality.load("pl"), quality.load("bs")
plq = {c: quality.quarterly_pl(v) for c, v in pl.items()}
periods = sorted({p for v in pl.values() for p in v})
known = {}
for d in sorted(R.date.unique()):
    k = [p for p in periods if margin.available(p) <= d]
    known[d] = k[-1] if k else None

NAMES = ["本業虧損", "獲利靠業外", "負債比偏高", "流動比率 < 100%", "淨值跌破面額", "累積虧損"]
rows = []
for r in R[["date", "code"]].itertuples():
    p = known.get(r.date)
    f = quality.flags(plq.get(r.code, {}), bs.get(r.code, {}), p) if p else {}
    has = r.code in pl and p in pl.get(r.code, {})
    rows.append([has] + [k in f for k in NAMES])
F = pd.DataFrame(rows, columns=["有財報"] + NAMES, index=R.index)
R = pd.concat([R, F], axis=1)
R["任一地雷"] = R[NAMES].any(axis=1)
R = R[R["有財報"]]   # 金融業等不在一般產業表裡的不算


def stat(d):
    if len(d) < 30:
        return {"n": int(len(d))}
    coh = d.groupby("i").x60.mean()
    return {"n": int(len(d)), "hit": round(d["飆股"].mean() * 100, 2), "x60": round(d.x60.mean() * 100, 2),
            "med60": round(d.ret60.median() * 100, 2), "crash": round(d["重挫"].mean() * 100, 1),
            "t": round(float(S.nw_t(coh.values, 3)), 2) if len(coh) > 12 else None}


out = {"span": [R.date.min(), R.date.max()], "share": {}, "test": {}}
print("=" * 110)
print("地雷股條件回測  %s ~ %s  樣本 %d" % (R.date.min(), R.date.max(), len(R)))
print("=" * 110)
for scope, base in (("全部股票", R), ("4★ 以上", R[R.stars >= 4])):
    print("\n[%s]  每個條件:有 vs 沒有(2019–22 / 2023 後)" % scope)
    out["test"][scope] = {}
    for k in NAMES + ["任一地雷"]:
        res = {}
        for tag, d in (("is", base[base.date < SPLIT]), ("oos", base[base.date >= SPLIT])):
            res[tag] = {"yes": stat(d[d[k]]), "no": stat(d[~d[k]])}
        out["test"][scope][k] = res
        out["share"].setdefault(scope, {})[k] = round(base[k].mean() * 100, 1)
        line = []
        for tag in ("is", "oos"):
            y, n = res[tag]["yes"], res[tag]["no"]
            if "hit" in y and "hit" in n:
                line.append("%s 有 n=%5d 比一般股 %+6.2f%% 曾跌25%% %4.1f%% | 沒有 %+6.2f%% %4.1f%%" % (
                    "19–22" if tag == "is" else "23– ", y["n"], y["x60"], y["crash"], n["x60"], n["crash"]))
            else:
                line.append("%s 樣本不足 n=%d" % ("19–22" if tag == "is" else "23– ", y["n"]))
        print("  %-12s 佔 %4.1f%%   %s" % (k, base[k].mean() * 100, "   ".join(line)))

with open(os.path.join(history.ROOT, "data", "radar", "landmine.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
