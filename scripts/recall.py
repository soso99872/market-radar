"""歷史飆股回顧:所有「120 個交易日內從低點翻倍」的波段,起漲雷達的規則抓不抓得到、抓到時已漲多少、之後還剩多少。

輸出 data/radar/recall.json(研究用,手動執行,不在每日排程裡)。
用法:python scripts/recall.py
"""
import json
import os

import numpy as np
import pandas as pd

import history
import radar
import signals as S

days = history.load_days()
F, hi, lo, taiex, names = S.frames(days)
close, chg = F["close"], F["chg"]
vyi = F["value"] / 1e8
dates = list(close.index)
codes = close.columns
rp = radar.revenue_panels(codes)
D = {k: radar.to_daily(rp[k], rp["months"], close.index) for k in ("good", "yoy3")}
trad = vyi >= radar.MIN_VALUE
avg20p = vyi.shift(1).rolling(20, min_periods=15).mean()
mx60 = close.shift(1).rolling(60, min_periods=50).max()
mn60 = close.shift(1).rolling(60, min_periods=50).min()
mx250 = close.shift(1).rolling(250, min_periods=200).max()
rev_on = (D["good"] == 1).fillna(False).values & trad.values
bo_on = ((vyi >= radar.SURGE * avg20p) & (chg >= 5) & trad & (close >= mx60) & (mx60 / mn60 - 1 <= 0.35)
         & (close >= mx250)).fillna(False).values
start = int(np.argmax(pd.to_datetime(close.index) >= pd.Timestamp(rp["months"][0][0], rp["months"][0][1], 1) + pd.DateOffset(months=13)))
Y3 = D["yoy3"].values
V = vyi.values
C = close.values

rows = []
for j, c in enumerate(codes):
    a = C[:, j]
    i = start
    n = len(a)
    while i < n - 1:
        if np.isnan(a[i]):
            i += 1
            continue
        w = a[i:i + 121]
        k = int(np.nanargmax(w))
        if w[k] >= 2 * a[i] and a[i] == np.nanmin(a[max(0, i - 20):i + 1]):
            pk = i + k
            tr = i + int(np.nanargmin(a[i:pk + 1]))
            if np.nanmean(V[max(0, tr - 20):tr + 1, j]) < 0.05:   # 幾乎沒成交的股票略過
                i = pk + 1
                continue
            r = {"code": c, "name": names.get(c, c), "trough": dates[tr], "peak": dates[pk],
                 "gain": round(float(a[pk] / a[tr] - 1) * 100), "yoy3_peak": None if np.isnan(Y3[pk, j]) else round(float(Y3[pk, j]))}
            for key, m in (("rev", rev_on), ("bo", bo_on)):
                pre = bool(m[max(0, tr - 20):tr + 1, j].any())
                hits = [q for q in range(tr, pk + 1) if m[q, j]]
                q0 = tr if pre else (hits[0] if hits else None)
                r[key] = None if q0 is None else {"date": dates[q0], "at": round(float(a[q0] / a[tr] - 1) * 100),
                                                  "left": round(float(a[pk] / a[q0] - 1) * 100), "pre": pre}
            rows.append(r)
            i = pk + 1
        else:
            i += 1

R = pd.DataFrame(rows)


def stats(df, key):
    at = df[key].map(lambda x: x["at"] if x else np.nan)
    left = df[key].map(lambda x: x["left"] if x else np.nan)
    caught = at.notna()
    return {"caught": round(caught.mean() * 100), "early": round((at <= 30).mean() * 100),
            "at_med": None if not caught.any() else round(at[caught].median()),
            "left_med": None if not caught.any() else round(left[caught].median())}


miss = R[~R.apply(lambda r: bool(r["rev"] or r["bo"]), axis=1)]
coverage = float((rev_on[start:].sum(axis=1) / np.maximum(trad.values[start:].sum(axis=1), 1)).mean() * 100)
doc = {
    "span": [dates[start], dates[-1]], "episodes": int(len(R)), "stocks": int(R.code.nunique()),
    "big": int((R.gain >= 200).sum()), "coverage": round(coverage, 1),
    "all": {"rev": stats(R, "rev"), "bo": stats(R, "bo")},
    "big3x": {"rev": stats(R[R.gain >= 200], "rev"), "bo": stats(R[R.gain >= 200], "bo")},
    "grow": {"n": int((R.yoy3_peak >= 20).sum()), "rev": stats(R[R.yoy3_peak >= 20], "rev")},
    "missed": {"n": int(len(miss)), "no_growth": int((miss.yoy3_peak < 0).sum()), "no_data": int(miss.yoy3_peak.isna().sum()),
               "mild_growth": int(((miss.yoy3_peak >= 0) & (miss.yoy3_peak < 20)).sum())},
    "by_year": {},
    "top": [],
}
for y, g in R.groupby(R.trough.str[:4]):
    doc["by_year"][y] = dict(n=int(len(g)), **stats(g, "rev"))
for _, r in R.sort_values("gain", ascending=False).head(40).iterrows():
    doc["top"].append({k: r[k] for k in ("code", "name", "trough", "peak", "gain", "yoy3_peak", "rev", "bo")})


def clean(o):
    """pandas 會把空值變成 NaN、整數變成 numpy 型別,轉成標準 JSON 能接受的值。"""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if np.isnan(o) else float(o)
    return o


with open(os.path.join(history.ROOT, "data", "radar", "recall.json"), "w", encoding="utf-8") as f:
    json.dump(clean(doc), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
print(json.dumps({k: doc[k] for k in ("span", "episodes", "stocks", "big", "coverage", "all", "big3x", "grow", "missed", "by_year")}, ensure_ascii=False, indent=1))
