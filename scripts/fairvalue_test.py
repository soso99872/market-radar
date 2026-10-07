"""模型合理價的回測:每月月底用「當時已知」的資料算每檔合理價,看潛在空間大的股票之後是否真的漲比較多。

用法:python scripts/fairvalue_test.py [起始日] [結束日]
"""
import sys

import numpy as np
import pandas as pd

import fairvalue as FV
import history
import radar
import signals as S
import valuation

START = sys.argv[1] if len(sys.argv) > 1 else "2000-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2100-01-01"

days = history.load_days()
F, hi, lo, taiex, names = S.frames(days)
close, opn = F["close"], F["open"]
vyi = F["value"] / 1e8
dates = list(close.index)
didx = {d: i for i, d in enumerate(dates)}
codes = list(close.columns)
rp = radar.revenue_panels(close.columns)
rev = rp["rev"]
months_r = rp["months"]
good = rp["good"]
VAL = valuation.load_all()
vm = sorted(VAL)
PE = pd.DataFrame({m: {c: v[0] for c, v in VAL[m]["s"].items()} for m in vm}).T
PB = pd.DataFrame({m: {c: v[1] for c, v in VAL[m]["s"].items()} for m in vm}).T

rows = []
for k, m in enumerate(vm):
    d = VAL[m]["date"]
    if not (START <= d <= END) or d not in didx or k < FV.MIN_HIST:
        continue
    i = didx[d]
    # 當時已公布的最新營收月份(次月 11 日起才算知道)
    known = [mm for mm in months_r if pd.Timestamp(mm[0] + (mm[1] == 12), mm[1] % 12 + 1, 11) <= pd.Timestamp(d)]
    if len(known) < 12:
        continue
    snap = VAL[m]["s"]
    pe_h, pb_h = PE.iloc[max(0, k - FV.MAX_HIST):k], PB.iloc[max(0, k - FV.MAX_HIST):k]
    rv = rev.loc[known]
    good_now = good.loc[known[-1]]
    for c, (pe, pb, _) in snap.items():
        if c not in close.columns:
            continue
        price = close.at[d, c]
        if pd.isna(price) or vyi.at[d, c] < 0.3:
            continue
        col = rv[c].dropna()
        ttm = r3 = None
        if len(col) >= 12 and col.index[-1] >= known[-2]:
            ttm, r3 = col.iloc[-12:].sum(), col.iloc[-3:].sum()
        est = FV.estimate(price, pe, pb, ttm, r3,
                          pe_h[c].tolist() if c in pe_h else [], pb_h[c].tolist() if c in pb_h else [])
        if not est:
            continue
        rows.append({"d": d, "i": i, "c": c, "up": est["fair"] / price - 1, "st": FV.status(price, est),
                     "method": est["method"], "radar": bool(good_now.get(c, False))})
R = pd.DataFrame(rows)
print("樣本:%d 筆、%d 個月、%s ~ %s" % (len(R), R.d.nunique(), R.d.min(), R.d.max()))
C, O = close.values, opn.values
cidx = {c: j for j, c in enumerate(close.columns)}
for h in (60, 120):
    R["x%d" % h] = np.nan
    for (d, i), g in R.groupby(["d", "i"]):
        if i + h >= len(dates):
            continue
        f = C[i + h] / O[i + 1] - 1 - S.COST
        univ = (vyi.values[i] >= 0.3) & ~np.isnan(f)
        R.loc[g.index, "x%d" % h] = f[[cidx[c] for c in g.c]] - np.nanmean(f[univ])
print("\n只算有未來報酬的樣本。「比一般股」= 之後 N 日報酬 − 同日所有可交易股票平均,已扣成本")
for h in (60, 120):
    col = "x%d" % h
    Q = R.dropna(subset=[col]).copy()
    if Q.empty:
        continue
    Q["q"] = Q.groupby("d")["up"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
    print("\n== 持有 %d 日 ==  (%d 個月)" % (h, Q.d.nunique()))
    print("  依潛在空間分 5 組(0 = 空間最小 / 最高估,4 = 空間最大 / 最低估)")
    for q, g in Q.groupby("q"):
        mon = g.groupby("d")[col].mean()
        print("   第 %d 組  空間中位 %+6.0f%%  比一般股 %+6.2f%%  中位 %+6.2f%%  月勝率 %3.0f%%  n=%d" % (
            q, g.up.median() * 100, g[col].mean() * 100, g[col].median() * 100, (mon > 0).mean() * 100, len(g)))
    spread = Q[Q.q == 4].groupby("d")[col].mean() - Q[Q.q == 0].groupby("d")[col].mean()
    t = S.nw_t(spread.dropna().values, max(1, h // 21))
    print("  最低估組 − 最高估組 每月平均 %+.2f%%, t = %+.2f, 為正的月份 %.0f%%" % (spread.mean() * 100, t, (spread > 0).mean() * 100))
    ic = Q.groupby("d").apply(lambda g: g.up.rank().corr(g[col].rank()))
    print("  排序相關係數(IC)平均 %+.3f,為正的月份 %.0f%%" % (ic.mean(), (ic > 0).mean() * 100))
    for st, g in Q.groupby("st"):
        print("   %s  比一般股 %+6.2f%%  中位 %+6.2f%%  n=%d" % (st, g[col].mean() * 100, g[col].median() * 100, len(g)))
    rq = Q[Q.radar]
    if len(rq) > 50:
        rq = rq.copy()
        rq["half"] = rq.groupby("d")["up"].transform(lambda s: s >= s.median())
        print("  起漲雷達名單內:")
        for hf, g in rq.groupby("half"):
            print("   潛在空間%s半  比一般股 %+6.2f%%  中位 %+6.2f%%  n=%d" % ("較大" if hf else "較小", g[col].mean() * 100, g[col].median() * 100, len(g)))
        for st, g in rq.groupby("st"):
            print("   名單內 %s  比一般股 %+6.2f%%  n=%d" % (st, g[col].mean() * 100, len(g)))
    for mt, g in Q.groupby("method"):
        print("   方法 %s  n=%d  比一般股 %+6.2f%%" % (mt, len(g), g[col].mean() * 100))

# 給網頁的摘要(持有 60 日;結論文字依結果自動產生,不事先寫好)
import json  # noqa: E402
import os  # noqa: E402

H = 60
col = "x%d" % H
Q = R.dropna(subset=[col]).copy()
Q["q"] = Q.groupby("d")["up"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
labels = ["空間最小(最貴)", "第 2 組", "第 3 組", "第 4 組", "空間最大(最便宜)"]
quint = []
for q, g in Q.groupby("q"):
    mon = g.groupby("d")[col].mean()
    quint.append({"label": labels[int(q)], "up_med": round(g.up.median() * 100, 1), "rel": round(g[col].mean() * 100, 2),
                  "med": round(g[col].median() * 100, 2), "mwin": round((mon > 0).mean() * 100, 0), "n": int(len(g))})
spread = Q[Q.q == 4].groupby("d")[col].mean() - Q[Q.q == 0].groupby("d")[col].mean()
t = S.nw_t(spread.dropna().values, max(1, H // 21))
rq = Q[Q.radar].copy()
inside = None
if len(rq) > 50:
    rq["half"] = rq.groupby("d")["up"].transform(lambda s: s >= s.median())
    inside = {"big": round(rq[rq.half][col].mean() * 100, 2), "small": round(rq[~rq.half][col].mean() * 100, 2)}
if t >= S.T_MID and spread.mean() > 0:
    verdict = "潛在空間最大的一組,之後 %d 日平均比最小的一組多 %.1f%%(t = %.1f,%.0f%% 的月份成立),排序有參考價值。" % (H, spread.mean() * 100, t, (spread > 0).mean() * 100)
elif spread.mean() > 0:
    verdict = "潛在空間大的組別之後平均較好(多 %.1f%%),但統計上不顯著(t = %.1f),只能當輔助參考,不要單靠它排序選股。" % (spread.mean() * 100, t)
else:
    verdict = "潛在空間大的股票之後並沒有比較好(最便宜一組比最貴一組 %+.1f%%,t = %.1f):在這段期間,這個合理價沒有預測力,請不要依它選股。" % (spread.mean() * 100, t)
if inside:
    verdict += " 在起漲雷達名單內,潛在空間較大的一半平均比一般股 %+.1f%%,較小的一半 %+.1f%%。" % (inside["big"], inside["small"])
doc = {"span": [Q.d.min(), Q.d.max()], "months": int(Q.d.nunique()), "hold": H, "quintiles": quint,
       "spread": round(spread.mean() * 100, 2), "t": round(t, 2), "inside_radar": inside, "verdict": verdict}
with open(os.path.join(history.ROOT, "data", "radar", "fv_backtest.json"), "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print("\n網頁摘要:", verdict)
