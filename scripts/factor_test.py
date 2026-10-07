"""起漲雷達名單內,哪些特徵能預測之後 60 日表現(用來決定「潛在空間」該怎麼排序)。

每個營收公告日,取名單內個股,計算各特徵的月度排序相關係數(IC)與前後半差距。
用法:python scripts/factor_test.py [起始日] [結束日]
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
H = 60

days = history.load_days()
F, hi, lo, taiex, names = S.frames(days)
close, opn, chg = F["close"], F["open"], F["chg"]
vyi = F["value"] / 1e8
dates = list(close.index)
N = len(dates)
rp = radar.revenue_panels(close.columns)
D = {k: radar.to_daily(rp[k], rp["months"], close.index) for k in ("good", "yoy", "yoy3", "streak", "mom")}
net = (F["fo"] + F["tr"] + F["de"]) * close / 1e8
feat = {
    "營收年增": D["yoy"],
    "3 月平均年增": D["yoy3"],
    "連續創新高月數": D["streak"],
    "營收月增": D["mom"],
    "20 日漲幅": close / close.shift(20) - 1,
    "60 日漲幅": close / close.shift(60) - 1,
    "距 52 週高點": close / close.rolling(250, min_periods=200).max() - 1,
    "離季線幅度": close / close.rolling(60, min_periods=40).mean() - 1,
    "成交規模(20 日均量)": vyi.rolling(20, min_periods=10).mean(),
    "60 日波動": chg.rolling(60, min_periods=40).std(),
    "20 日法人買超/成交": net.rolling(20).sum() / vyi.rolling(20).sum(),
}
# 估值:用每月快照的本益比相對自己歷史中位數(只用當時以前的資料)
VAL = valuation.load_all()
vm = sorted(VAL)
PE = pd.DataFrame({m: {c: v[0] for c, v in VAL[m]["s"].items()} for m in vm}).T.reindex(columns=close.columns)
pe_rel = PE / PE.shift(1).rolling(FV.MAX_HIST, min_periods=FV.MIN_HIST).median()
pe_rel.index = [pd.Timestamp(VAL[m]["date"]) for m in vm]
feat["本益比相對歷史"] = pe_rel.reindex(pd.to_datetime(close.index), method="ffill").set_axis(close.index)

pub = []
for y, m in rp["months"]:
    i = int(pd.to_datetime(close.index).searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11)))
    if 0 < i < N - H - 1 and START <= dates[i] <= END:
        pub.append(i)
G = (D["good"] == 1).values
rows = []
for i in sorted(set(pub)):
    f = close.values[i + H] / opn.values[i + 1] - 1 - S.COST
    univ = (vyi.values[i] >= 0.3) & ~np.isnan(f)
    bench = np.nanmean(f[univ])
    js = np.where(G[i] & univ)[0]
    for j in js:
        r = {"i": i, "x": f[j] - bench}
        for k, v in feat.items():
            r[k] = v.values[i, j]
        rows.append(r)
R = pd.DataFrame(rows)
print("期間 %s ~ %s,%d 個公告日,名單內 %d 筆" % (dates[min(pub)], dates[max(pub)], R.i.nunique(), len(R)))
print("%-20s %8s %8s %10s %10s %8s" % ("特徵", "IC平均", "IC>0月", "高半-低半", "t", "樣本"))
out = []
for k in feat:
    Q = R.dropna(subset=[k])
    ic = Q.groupby("i").apply(lambda g: g[k].rank().corr(g.x.rank()) if len(g) >= 8 else np.nan).dropna()
    sp = Q.groupby("i").apply(lambda g: g[g[k] >= g[k].median()].x.mean() - g[g[k] < g[k].median()].x.mean() if len(g) >= 8 else np.nan).dropna()
    t = S.nw_t(sp.values, 3)
    out.append((k, ic.mean(), (ic > 0).mean(), sp.mean(), t, len(Q)))
for k, a, b, c, t, n in sorted(out, key=lambda x: -abs(x[4])):
    print("%-20s %+8.3f %7.0f%% %+9.2f%% %+9.2f %8d" % (k, a, b * 100, c * 100, t, n))
