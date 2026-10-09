"""評級準確度的補充回測(研究用,不在每日排程裡跑)。樣本來自 explosion_study.py(先跑它)。

借鏡競品的做法逐一檢驗,看能不能讓評級更準:
  1 FinLab 月營收動能規則(近 3 月平均營收 > 近 12 月平均,且股價站上 20/60/120 日均線),與我們的 A 層互相驗證
  2 IBD 的 RS 評等:過去 250 日漲幅在全市場的百分位,取代「60 日漲 ≥ 20%」的固定門檻(多空不同時期門檻是否更穩)
  3 大盤多空:加權指數在 60 日均線上 / 下時,星等是否都有效
  4 財報狗「成長股健診」的毛利年增 > 0:加進來是否更好
  5 集中:像 FinLab 只買動能最強的 10 檔,和買全部 4★ 以上比較
  6 逐年穩定性,以及「每月買 4★ 以上、持有到下個月」的年化報酬、最大回撤,對照全部可交易股票等權

用法:python scripts/accuracy_study.py > 報告.txt
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

# 樣本是 explosion_study.py 在本機產生的暫存檔,不是外部資料
R = pd.read_pickle(os.path.join(os.environ.get("TEMP", "/tmp"), "mr_samples.pkl"))
print("載入歷史資料…", file=sys.stderr)
days = history.load_days()
F, HI, LO, taiex, names = S.frames(days)
close, opn = F["close"], F["open"]
vyi = F["value"] / 1e8
dates = list(close.index)
codes = list(close.columns)
cix = {c: j for j, c in enumerate(codes)}
N = len(dates)
C, O, V = close.values, opn.values, vyi.values
rp = radar.revenue_panels(close.columns)
SPLIT = "2023-01-01"
OUT = os.path.join(history.ROOT, "data", "radar", "accuracy.json")
out = {}


def at(df, mat):
    return np.array([mat[i, cix[c]] for i, c in zip(df.i, df.code)])


def stat(d):
    if len(d) < 30:
        return {"n": int(len(d))}
    coh = d.groupby("i").x60.mean()
    return {"n": int(len(d)), "per_month": round(len(d) / max(1, d.i.nunique()), 1), "hit": round(d["飆股"].mean() * 100, 2),
            "x60": round(d.x60.mean() * 100, 2), "med60": round(d.ret60.median() * 100, 2), "crash": round(d["重挫"].mean() * 100, 1),
            "t": round(float(S.nw_t(coh.values, 3)), 2) if len(coh) > 12 else None}


def line(label, m, key=None):
    a, b = stat(R[m & (R.date < SPLIT)]), stat(R[m & (R.date >= SPLIT)])
    if key:
        out.setdefault(key, {})[label] = {"is": a, "oos": b}
    for tag, s in (("2019–22", a), ("2023– ", b)):
        if "hit" in s:
            print("  %-36s %s 每月 %6.1f 檔  飆股 %5.2f%%  60日比一般股 %+6.2f%%  中位 %+6.2f%%  曾跌25%% %4.1f%%  t=%s" % (
                label, tag, s["per_month"], s["hit"], s["x60"], s["med60"], s["crash"], s["t"]))
        else:
            print("  %-36s %s 樣本不足 n=%d" % (label, tag, s["n"]))


# ---- 特徵 ----
ma = {n: close.rolling(n, min_periods=int(n * 0.8)).mean().values for n in (20, 60, 120)}
above_all = (C > ma[20]) & (C > ma[60]) & (C > ma[120])
ret250 = (close / close.shift(250) - 1)
rs = ret250.where(vyi >= radar.MIN_VALUE).rank(axis=1, pct=True).values * 100   # 全市場百分位(只比可交易股票)
rev = rp["rev"]
fin_rev = radar.to_daily((rev.rolling(3, min_periods=3).mean() > rev.rolling(12, min_periods=12).mean()).astype(float),
                         rp["months"], close.index).values == 1
tx = taiex.values
tx_up = tx > pd.Series(tx).rolling(60, min_periods=40).mean().values
R["站上三線"] = at(R, above_all)
R["RS"] = at(R, rs)
R["FinLab營收"] = at(R, fin_rev.astype(float)) == 1
R["大盤多頭"] = [bool(tx_up[i]) for i in R.i]
# 毛利年增(最新已過申報期限的一季,與去年同季比)
cum = margin.load()
periods = sorted({p for v in cum.values() for p in v})
gpq = {c: {p: g for p, (r, g) in margin.quarterly(v).items()} for c, v in cum.items()}
known_p = {}
for i in sorted(R.i.unique()):
    k = [p for p in periods if margin.available(p) <= dates[i]]
    known_p[i] = k[-1] if k else None


def gp_yoy(i, c):
    p = known_p.get(i)
    g = gpq.get(c)
    if not p or not g or p not in g:
        return np.nan
    py = "%d%s" % (int(p[:4]) - 1, p[4:])
    return (g[p] / g[py] - 1) * 100 if py in g and g[py] and g[py] > 0 else np.nan


R["毛利年增"] = [gp_yoy(i, c) for i, c in zip(R.i, R.code)]
S5, S4 = R.stars >= 5, R.stars >= 4

print("=" * 110)
print("評級準確度補充回測  %s ~ %s  2019–22 決定規則,2023 後樣本外" % (R.date.min(), R.date.max()))
print("=" * 110)

print("\n[1] FinLab 月營收動能規則 vs 我們的 A 層")
fin = R["FinLab營收"] & R["站上三線"]
line("FinLab 規則(營收 3>12 月均 + 站上三線)", fin, "finlab")
line("我們的 5★", S5, "finlab")
line("兩者都符合", fin & S5, "finlab")
line("FinLab 有、我們沒有(4★ 以下)", fin & ~S4, "finlab")

print("\n[2] 動能門檻:60 日漲 ≥ 20% vs RS 評等(250 日漲幅全市場百分位)")
base = R.rev & (R["同產業60日漲幅"] >= 15)
line("營收+題材+60 日漲 ≥ 20%(目前)", base & (R["60日漲幅"] >= 20), "rs")
for th in (70, 80, 90):
    line("營收+題材+RS ≥ %d" % th, base & (R.RS >= th), "rs")
line("營收+題材+60 日 ≥ 20% 且 RS ≥ 80", base & (R["60日漲幅"] >= 20) & (R.RS >= 80), "rs")

print("\n[3] 大盤多空(加權指數 vs 60 日均線)")
for lab, m in (("大盤多頭", R["大盤多頭"]), ("大盤空頭", ~R["大盤多頭"])):
    line("5★ · " + lab, S5 & m, "regime")
    line("4★ 以上 · " + lab, S4 & m, "regime")
    line("全部股票 · " + lab, m, "regime")

print("\n[4] 毛利年增 > 0(財報狗成長股條件)")
line("4★ 以上", S4, "gp")
line("4★ 以上 且 毛利年增 > 0", S4 & (R["毛利年增"] > 0), "gp")
line("4★ 以上 且 毛利年增 ≤ 0", S4 & (R["毛利年增"] <= 0), "gp")
line("4★ 以上 且 毛利年增 > 營收年增", S4 & (R["毛利年增"] > R["近3月年增"]), "gp")

print("\n[5] 集中 vs 分散:4★ 以上中依 RS 取前 10 檔")
R["rk"] = R[S4].groupby("i").RS.rank(ascending=False, method="first")
line("4★ 以上全部", S4, "conc")
line("4★ 以上 RS 前 10 檔", S4 & (R.rk <= 10), "conc")
line("4★ 以上 RS 第 11 名以後", S4 & (R.rk > 10), "conc")

# ---- 6 逐年 + 月度組合績效 ----
print("\n[6] 逐年:4★ 以上 vs 全部股票(60 日比一般股、飆股率)")
R["year"] = R.date.str[:4]
out["years"] = {}
for y, g in R.groupby("year"):
    a, b = stat(g[g.stars >= 4]), stat(g[g.stars >= 5])
    out["years"][y] = {"s4": a, "s5": b}
    if "hit" in a:
        print("  %s  4★+ 每月 %5.1f 檔 飆股 %5.2f%% 60日比一般股 %+6.2f%%   5★ %s" % (
            y, a["per_month"], a["hit"], a["x60"], ("飆股 %5.2f%% 比一般股 %+6.2f%%" % (b["hit"], b["x60"])) if "hit" in b else "樣本不足"))

print("\n[6b] 每月營收公告隔天進場、持有到下一次公告(約 1 個月),等權、扣成本")
pubs = sorted(R.i.unique())
curves = {"4★ 以上": [], "5★": [], "全部可交易股票": [], "加權指數": []}
for k, i in enumerate(pubs[:-1]):
    e, x = i + 1, pubs[k + 1] + 1
    if x >= N:
        break
    f = C[x - 1] / O[e] - 1 - S.COST
    ok = (V[i] >= radar.MIN_VALUE) & ~np.isnan(f)
    g = R[R.i == i]
    for lab, sel in (("4★ 以上", g[g.stars >= 4]), ("5★", g[g.stars >= 5])):
        js = [cix[c] for c in sel.code if ok[cix[c]]]
        curves[lab].append((dates[e], float(np.mean(f[js])) if js else 0.0))
    curves["全部可交易股票"].append((dates[e], float(np.nanmean(f[ok]))))
    # 加權指數(價格指數、不含股利;進出場用同樣兩天的收盤近似,沒有開盤價)
    curves["加權指數"].append((dates[e], float(tx[x - 1] / tx[i] - 1) if tx[i] and not np.isnan(tx[x - 1]) else 0.0))
out["curve"] = {}
for lab, cv in curves.items():
    r = np.array([v for _, v in cv])
    eq = np.cumprod(1 + r)
    yrs = len(r) / 12
    cagr = eq[-1] ** (1 / yrs) - 1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    sharpe = r.mean() / r.std() * math.sqrt(12) if r.std() else 0
    win = (r > 0).mean()
    out["curve"][lab] = {"cagr": round(cagr * 100, 1), "mdd": round(mdd * 100, 1), "sharpe": round(float(sharpe), 2), "win": round(win * 100, 0),
                         "months": len(r), "eq": [[d, round(float(v), 3)] for (d, _), v in zip(cv, eq)]}
    print("  %-14s %d 個月  年化 %+6.1f%%  最大回撤 %6.1f%%  月夏普(年化) %.2f  月勝率 %.0f%%" % (lab, len(r), cagr * 100, mdd * 100, sharpe, win * 100))

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
