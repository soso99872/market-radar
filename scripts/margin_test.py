"""毛利率變化對營收動能名單的影響(研究用,不在每日排程裡跑)。

問題:營收創新高、年增高,但毛利率在下降(多半是降價搶量、低毛利產品變多),股價之後是否比較差?

做法:在每個營收公告日,取當時「已經過申報期限」的最新一季毛利率(見 margin.py,一律用期限日,不偷看),
  毛利率年變化 = 最新一季毛利率 − 去年同季毛利率(百分點,避開季節性)
依此把營收動能名單分成 下降 / 持平 / 上升 三組,比較公告後隔天開盤進場、持有 60 日的表現。
同樣的分組也套在全部股票上,看毛利率本身有沒有預測力。
報酬都已扣交易成本;「比一般股」= 減掉同日所有可交易股票的平均。

用法:python scripts/margin_test.py > 報告.txt
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

import history
import margin
import radar
import signals as S

TH = 1.0   # 毛利率年變化超過 ±1 個百分點才算上升 / 下降
H = 60

print("載入歷史資料…", file=sys.stderr)
days = history.load_days()
F, hi, lo, taiex, names = S.frames(days)
close, opn = F["close"], F["open"]
vyi = F["value"] / 1e8
dates = list(close.index)
codes = list(close.columns)
N = len(dates)
rp = radar.revenue_panels(close.columns)
months = rp["months"]
pdates = pd.to_datetime(close.index)
C, O, V = close.values, opn.values, vyi.values

pub_i = []
for y, m in months:
    i = int(pdates.searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11)))
    if 0 < i < N:
        pub_i.append(i)
pub_i = sorted(set(pub_i))

# 營收動能條件(直接用 radar.py 的定義)
REV = radar.to_daily(rp["good"].astype(float), months, close.index).values == 1
YOY3 = radar.to_daily(rp["yoy3"], months, close.index).values

# ---- 毛利率:每個公告日當時可取得的最新一季 ----
cum = margin.load()
periods = sorted({p for v in cum.values() for p in v})
avail = {p: margin.available(p) for p in periods}
GM = {}       # 代號 → {期別: 毛利率%}
GPY = {}      # 代號 → {期別: 毛利}
for c, v in cum.items():
    q = margin.quarterly(v)
    GM[c] = {p: g / r * 100 for p, (r, g) in q.items() if r and r > 0}
    GPY[c] = {p: g for p, (r, g) in q.items()}


def prev_year(p):
    return "%d%s" % (int(p[:4]) - 1, p[4:])


def margin_state(i):
    """回傳 (毛利率年變化 pp 陣列, 毛利年增 % 陣列, 使用的期別)。"""
    d = dates[i]
    known = [p for p in periods if avail[p] <= d]
    if not known:
        return None, None, None
    p = known[-1]
    dgm = np.full(len(codes), np.nan)
    gpg = np.full(len(codes), np.nan)
    for j, c in enumerate(codes):
        g = GM.get(c)
        if not g or p not in g or prev_year(p) not in g:
            continue
        dgm[j] = g[p] - g[prev_year(p)]
        a, b = GPY[c][p], GPY[c][prev_year(p)]
        if b and b > 0:
            gpg[j] = (a / b - 1) * 100
    return dgm, gpg, p


rows = []
for i in pub_i:
    e = i + 1
    if e + H - 1 >= N:
        continue
    dgm, gpg, p = margin_state(i)
    if p is None:
        continue
    f = C[e + H - 1] / O[e] - 1 - S.COST
    ok = (V[i] >= radar.MIN_VALUE) & ~np.isnan(f)
    if ok.sum() < 50:
        continue
    bench = np.nanmean(f[ok])
    for j in np.where(ok)[0]:
        rows.append((i, dates[i], codes[j], bool(REV[i, j]), dgm[j], gpg[j], YOY3[i, j], f[j], f[j] - bench, p))

R = pd.DataFrame(rows, columns=["i", "date", "code", "rev", "dgm", "gpg", "yoy3", "ret", "x", "period"])
R = R[R.dgm.notna() & (R.dgm.abs() <= 50)]   # 營收極小的公司毛利率會失真(例如 −7000 pp),排除
R["grp"] = np.where(R.dgm <= -TH, "下降", np.where(R.dgm >= TH, "上升", "持平"))


def stat(df):
    if len(df) < 30:
        return {"n": len(df)}
    coh = df.groupby("i").x.mean()
    t = S.nw_t(coh.values, max(1, math.ceil(H / 21)))
    return {"n": len(df), "x": round(df.x.mean() * 100, 2), "med": round(df.ret.median() * 100, 2),
            "win": round((df.x > 0).mean() * 100, 1), "loss15": round((df.ret <= -0.15).mean() * 100, 1),
            "dbl": round((df.ret >= 1).mean() * 100, 2), "t": round(float(t), 2), "months": len(coh)}


def diff_t(a, b):
    """兩組每月平均超額報酬的差,用月份配對後的 Newey-West t。"""
    ca, cb = a.groupby("i").x.mean(), b.groupby("i").x.mean()
    both = ca.index.intersection(cb.index)
    d = (ca[both] - cb[both]).values
    if len(d) < 12:
        return None, None
    return round(d.mean() * 100, 2), round(float(S.nw_t(d, max(1, math.ceil(H / 21)))), 2)


def fmt(s):
    if "x" not in s:
        return "樣本不足 n=%d" % s["n"]
    return "n=%5d  比一般股 %+6.2f%%  中位(絕對) %+6.2f%%  勝過一般股 %4.1f%%  虧超15%% %4.1f%%  翻倍 %4.2f%%  t=%+5.2f" % (
        s["n"], s["x"], s["med"], s["win"], s["loss15"], s["dbl"], s["t"])


out = {"span": [R.date.min(), R.date.max()], "th": TH, "h": H}
print("=" * 110)
print("毛利率變化回測  %s ~ %s  持有 %d 日  毛利率年變化 ±%.0f pp 為界" % (R.date.min(), R.date.max(), H, TH))
print("=" * 110)
for label, sub in (("營收動能名單", R[R.rev]), ("全部可交易股票", R)):
    print("\n[%s]" % label)
    out[label] = {}
    for g in ("上升", "持平", "下降"):
        s = stat(sub[sub.grp == g])
        out[label][g] = s
        print("  毛利率%s  %s" % (g, fmt(s)))
    m, t = diff_t(sub[sub.grp == "下降"], sub[sub.grp == "上升"])
    out[label]["下降減上升"] = [m, t]
    print("  下降 − 上升:每月平均差 %s pp,t=%s" % (m, t))

print("\n[營收動能名單 · 分段]")
L = R[R.rev]
out["分段"] = {}
for a, b in (("2019-01-01", "2022-12-31"), ("2023-01-01", "2100-01-01")):
    seg = L[(L.date >= a) & (L.date <= b)]
    m, t = diff_t(seg[seg.grp == "下降"], seg[seg.grp == "上升"])
    out["分段"][a[:4]] = {g: stat(seg[seg.grp == g]) for g in ("上升", "下降")}
    out["分段"][a[:4]]["diff"] = [m, t]
    print("  %s~  上升 %s\n         下降 %s\n         下降 − 上升 %s pp, t=%s" % (
        a[:4], fmt(stat(seg[seg.grp == "上升"])), fmt(stat(seg[seg.grp == "下降"])), m, t))

print("\n[營收動能名單 · 毛利成長跟不上營收]")
# 毛利年增 < 近 3 月營收年增 − 10 個百分點 → 營收成長沒有轉成毛利
lag = L[L.gpg.notna() & L.yoy3.notna()]
weak = lag[lag.gpg < lag.yoy3 - 10]
strong = lag[lag.gpg >= lag.yoy3 - 10]
out["毛利跟上"] = {"跟上": stat(strong), "落後": stat(weak), "diff": list(diff_t(weak, strong))}
print("  毛利成長跟上營收  %s" % fmt(stat(strong)))
print("  毛利成長落後營收  %s" % fmt(stat(weak)))
print("  落後 − 跟上:%s pp, t=%s" % tuple(diff_t(weak, strong)))

print("\n[毛利率年變化五等分 · 營收動能名單]")
q = pd.qcut(L.dgm, 5, labels=False, duplicates="drop")
out["五等分"] = []
for k in sorted(q.unique()):
    sub = L[q == k]
    s = stat(sub)
    s["range"] = [round(sub.dgm.min(), 1), round(sub.dgm.max(), 1)]
    out["五等分"].append(s)
    print("  Q%d  %+6.1f ~ %+6.1f pp  %s" % (k + 1, s["range"][0], s["range"][1], fmt(s)))

with open(os.path.join(history.ROOT, "data", "radar", "margin_test.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
