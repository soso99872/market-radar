"""技術指標回測(研究用,不在每日排程裡跑)。樣本來自 explosion_study.py(先跑它)。

問題:台股常用的技術訊號(均線排列、KD、RSI、MACD、布林通道、量價、缺口),在每個營收公告日當下成立的股票,
之後 60 日是否比一般股好、大跌機率是否不同?在全部股票、以及評級 4★ 以上兩個範圍各看一次,
2019–22 與 2023 後分開(兩段方向一致才算有用)。只有回測有用的,才在個股健檢裡標「有回測依據」。
「最近 5 日內發生」的事件型訊號(交叉、缺口),只看公告日前 5 個交易日內是否出現。

用法:python scripts/technical_test.py > 報告.txt   (另寫 data/radar/technical.json)
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import history
import signals as S
import technical

# 樣本是 explosion_study.py 在本機產生的暫存檔,不是外部資料
R = pd.read_pickle(os.path.join(os.environ.get("TEMP", "/tmp"), "mr_samples.pkl"))
print("載入歷史資料…", file=sys.stderr)
days = history.load_days()
F, HI, LO, taiex, names = S.frames(days)
C = F["close"]
vol = F["value"]
codes = list(C.columns)
cix = {c: j for j, c in enumerate(codes)}
SPLIT = "2023-01-01"


def indicators():
    """回傳 {名稱: 日期 × 代號 的布林矩陣};公式在 scripts/technical.py(與每日排程共用)。"""
    sig, _ = technical.compute(C, HI, LO, vol)
    return {k: v.values for k, v in sig.items()}


IND = indicators()
for k, m in IND.items():
    R[k] = [bool(m[i, cix[c]]) for i, c in zip(R.i, R.code)]


def stat(d):
    if len(d) < 50:
        return {"n": int(len(d))}
    coh = d.groupby("i").x60.mean()
    return {"n": int(len(d)), "hit": round(d["飆股"].mean() * 100, 2), "x60": round(d.x60.mean() * 100, 2),
            "med60": round(d.ret60.median() * 100, 2), "crash": round(d["重挫"].mean() * 100, 1),
            "t": round(float(S.nw_t(coh.values, 3)), 2) if len(coh) > 12 else None}


out = {"span": [R.date.min(), R.date.max()], "test": {}}
print("=" * 120)
print("技術指標回測  %s ~ %s  樣本 %d" % (R.date.min(), R.date.max(), len(R)))
print("每列:成立 vs 不成立 的 60 日比一般股(及 60 日內曾跌 25%% 比例),2019–22 | 2023 後")
print("=" * 120)
for scope, base in (("全部股票", R), ("4★ 以上", R[R.stars >= 4])):
    print("\n[%s]" % scope)
    out["test"][scope] = {}
    for k in IND:
        res = {t: {"yes": stat(d[d[k]]), "no": stat(d[~d[k]])}
               for t, d in (("is", base[base.date < SPLIT]), ("oos", base[base.date >= SPLIT]))}
        out["test"][scope][k] = res
        cells = []
        for t in ("is", "oos"):
            y, n = res[t]["yes"], res[t]["no"]
            cells.append("%+6.2f%% (%4.1f%%) vs %+6.2f%% (%4.1f%%) n=%5d" % (y["x60"], y["crash"], n["x60"], n["crash"], y["n"]) if "x60" in y and "x60" in n
                         else "樣本不足 n=%d" % y["n"])
        print("  %-30s 佔 %4.1f%%  %s | %s" % (k, base[k].mean() * 100, cells[0], cells[1]))

with open(os.path.join(history.ROOT, "data", "radar", "technical.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
