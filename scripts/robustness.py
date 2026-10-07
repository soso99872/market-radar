"""起漲雷達規則的穩健性回測(研究用,不在每日排程裡跑)。

用法:python scripts/robustness.py [起始日] [結束日] > 報告.txt
檢驗項目:
  A 參數敏感度   年增門檻、創新高的回看月數 —— 好的規則應該是一片高原,不是單一尖峰
  B 持有天數     5 ~ 120 日
  C 進場延遲     公告後隔天 / 3 / 5 / 10 天才進場 —— 優勢消失得多快
  D 執行現實     開盤漲停買不到、額外滑價、流動性門檻
  E 分段         半年度、大盤多空、規模大小
  F 安慰劑       同一天隨機抽同樣多檔 × 300 次;用一年前的舊營收 —— 實際結果要明顯優於這些
  G 下市股       持有期間下市的股票視為全損時的影響
  H 每月一籃     月勝率、最差月份、最長連輸
  I 產業循環     門檻敏感度
所有報酬都已扣交易成本,主要指標是「比同日一般股多賺多少」(同日所有可交易股票的平均)。
"""
import math
import sys

import numpy as np
import pandas as pd

import history
import radar
import signals as S

START = sys.argv[1] if len(sys.argv) > 1 else "2000-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2100-01-01"

print("載入歷史資料…", file=sys.stderr)
days = history.load_days()
F, hi, lo, taiex, names = S.frames(days)
close, opn, chg = F["close"], F["open"], F["chg"]
vyi = F["value"] / 1e8
dates = list(close.index)
codes = close.columns
N = len(dates)
rp = radar.revenue_panels(codes)
months = rp["months"]
pdates = pd.to_datetime(close.index)

# 營收公告日(視為次月 11 日後第一個交易日)
pub_i = []
for y, m in months:
    i = int(pdates.searchsorted(pd.Timestamp(y + (m == 12), m % 12 + 1, 11)))
    if 0 < i < N:
        pub_i.append(i)
pub_i = sorted(set(pub_i))
in_range = [i for i in pub_i if START <= dates[i] <= END]
avg20 = vyi.rolling(20, min_periods=10).mean()
C, O, V = close.values, opn.values, vyi.values
A20 = avg20.values
TX = taiex.values
taiex_ma60 = taiex.rolling(60, min_periods=40).mean().values


def daily(panel):
    return radar.to_daily(panel, months, close.index).values


def rev_cond(yoy_th=30, win=12, alt=True, alt_th=20, lag=0):
    rev, yoy = rp["rev"].shift(lag), rp["yoy"].shift(lag)
    rmax = rev.shift(1).rolling(win, min_periods=max(3, int(win * 0.8))).max()
    rec = (rev >= rmax) & rev.notna()
    good = rec & (yoy >= yoy_th)
    if alt:
        good = good | (rec & (yoy >= alt_th) & (yoy.shift(1) >= alt_th))
    return daily(good.astype(float)) == 1


def evaluate(cond, h=60, delay=0, min_val=0.3, slip=0.0, skip_limit=False, rows=None, delist_loss=False, mask=None):
    """cond:日期 × 代號 的布林矩陣(訊號狀態),只在營收公告日取樣。回傳每一筆的超額報酬與日期。"""
    out_x, out_r, out_i = [], [], []
    for i in (rows if rows is not None else in_range):
        e = i + 1 + delay
        if e + h - 1 >= N:
            continue
        x_ = e + h - 1
        trad = V[i] >= min_val
        entry, exitp = O[e], C[x_]
        f = exitp / entry - 1 - S.COST
        if delist_loss:   # 進場後到期前消失(下市)的股票,視為全損
            gone = ~np.isnan(entry) & np.isnan(exitp)
            f = np.where(gone, -1.0, f)
        ok_univ = trad & ~np.isnan(f)
        if ok_univ.sum() < 50:
            continue
        bench = np.nanmean(f[ok_univ])
        pick = cond[i] & ok_univ
        if mask is not None:
            pick &= mask[i]
        if skip_limit:   # 進場當天開盤就漲停(≥ +9.5%)買不到
            prev = C[e - 1]
            pick &= ~(O[e] >= prev * 1.095)
        js = np.where(pick)[0]
        out_x += list(f[js] - slip - bench)   # 滑價只算在自己買的股票上,一般股基準不受影響
        out_r += list(f[js] - slip)
        out_i += [i] * len(js)
    return np.array(out_x), np.array(out_r), np.array(out_i)


def summary(x, r, ii, h=60, by_day=False):
    if len(x) < 20:
        return "樣本不足(n=%d)" % len(x)
    cohort = pd.Series(x).groupby(ii).mean()
    if by_day:   # 每天都可能觸發的訊號:依觸發日聚合,重疊天數 = 持有天數
        t = S.nw_t(cohort.values, h)
        return "n=%5d  比一般股 %+6.2f%%  中位(絕對) %+6.2f%%  勝過一般股 %4.1f%%  t=%+5.2f  (%d 個觸發日)" % (
            len(x), x.mean() * 100, np.median(r) * 100, (x > 0).mean() * 100, t, len(cohort))
    t = S.nw_t(cohort.values, max(1, math.ceil(h / 21)))
    return "n=%5d  比一般股 %+6.2f%%  中位(絕對) %+6.2f%%  勝過一般股 %4.1f%%  t=%+5.2f  月勝率 %3.0f%% (%d 個月)" % (
        len(x), x.mean() * 100, np.median(r) * 100, (x > 0).mean() * 100, t, (cohort > 0).mean() * 100, len(cohort))


def line(label, cond, by_day=False, **kw):
    h = kw.get("h", 60)
    x, r, ii = evaluate(cond, **kw)
    print("  %-34s %s" % (label, summary(x, r, ii, h, by_day)))
    return x, r, ii


print("=" * 100)
print("起漲雷達穩健性回測  期間 %s ~ %s(營收公告日 %d 次)" % (dates[in_range[0]] if in_range else "-",
                                                    dates[in_range[-1]] if in_range else "-", len(in_range)))
print("基準規則:營收創 12 月新高,且年增 ≥ 30% 或連 2 月年增 ≥ 20%;公告後隔天開盤進場,持有 60 日")
print("=" * 100)
BASE = rev_cond()
everything = np.ones_like(BASE, dtype=bool)
print("\n[基準]")
line("所有可交易股票(對照)", everything)
bx, br, bi = line("基準規則", BASE)

print("\n[A 參數敏感度:年增門檻 × 創新高回看月數](不含連 2 月條件)")
for win in (6, 12, 24):
    for th in (10, 20, 30, 40, 50, 80):
        line("創 %2d 月新高、年增 ≥ %d%%" % (win, th), rev_cond(th, win, alt=False))
print("  只看年增、不要求創新高:")
for th in (20, 30, 50):
    y = daily((rp["yoy"] >= th).astype(float)) == 1
    line("年增 ≥ %d%%(不看新高)" % th, y)
line("只要創 12 月新高(不看年增)", daily(((rp["rev"] >= rp["rev"].shift(1).rolling(12, min_periods=10).max()) & rp["rev"].notna()).astype(float)) == 1)

print("\n[B 持有天數]")
for h in (5, 10, 20, 40, 60, 90, 120):
    line("持有 %d 日" % h, BASE, h=h)

print("\n[C 進場延遲](公告後隔天開盤 = 0)")
for dl in (0, 2, 4, 9, 19):
    line("延後 %d 個交易日進場" % dl, BASE, delay=dl)

print("\n[D 執行現實]")
line("開盤漲停買不到就放棄", BASE, skip_limit=True)
line("額外滑價 0.5%", BASE, slip=0.005)
line("額外滑價 1%", BASE, slip=0.01)
for mv in (0.1, 0.3, 1, 3):
    line("當天成交 ≥ %.1f 億才算" % mv, BASE, min_val=mv)

print("\n[E 分段]")
halves = {}
for i in in_range:
    k = dates[i][:4] + ("H1" if dates[i][5:7] <= "06" else "H2")
    halves.setdefault(k, []).append(i)
for k, rows in sorted(halves.items()):
    line("半年 %s" % k, BASE, rows=rows)
bull = [i for i in in_range if TX[i] > taiex_ma60[i]]
bear = [i for i in in_range if not TX[i] > taiex_ma60[i]]
line("大盤在季線上(多頭)", BASE, rows=bull)
line("大盤在季線下(空頭)", BASE, rows=bear)
q = np.nanquantile(np.where(V >= 0.3, A20, np.nan), [1 / 3, 2 / 3])   # 只在可交易股票裡分大中小
print("  (20 日均量分界:%.2f 億 / %.2f 億)" % (q[0], q[1]))
line("小型(20日均量後 1/3)", BASE, mask=A20 < q[0])
line("中型", BASE, mask=(A20 >= q[0]) & (A20 < q[1]))
line("大型(前 1/3)", BASE, mask=A20 >= q[1])

print("\n[F 安慰劑檢定]")
rng = np.random.default_rng(1)
counts = {}
for xi in bi:
    counts[xi] = counts.get(xi, 0) + 1
null = []
for _ in range(300):
    xs = []
    for i, k in counts.items():
        e, x_ = i + 1, i + 60
        f = C[x_] / O[e] - 1 - S.COST
        ok = (V[i] >= 0.3) & ~np.isnan(f)
        js = rng.choice(np.where(ok)[0], min(k, ok.sum()), replace=False)
        xs += list(f[js] - np.nanmean(f[ok]))
    null.append(np.mean(xs))
null = np.array(null)
print("  隨機抽同樣多檔 × 300 次:平均比一般股 %+.2f%%,最好的一次 %+.2f%%;實際規則 %+.2f%%,勝過 %d/300 次隨機" % (
    null.mean() * 100, null.max() * 100, bx.mean() * 100, (bx.mean() > null).sum()))
line("舊消息:用 12 個月前的營收", rev_cond(lag=12))
line("舊消息:用 3 個月前的營收", rev_cond(lag=3))

print("\n[G 下市股處理]")
x0, _, _ = evaluate(BASE)
x1, r1, i1 = evaluate(BASE, delist_loss=True)
print("  持有期間消失的筆數:%d;視為全損後比一般股 %+.2f%%(原 %+.2f%%)" % (len(x1) - len(x0), x1.mean() * 100, x0.mean() * 100))

print("\n[H 每月一籃(名單全部等權,持有 20 日,不重疊)]")
x, r, ii = evaluate(BASE, h=20)
cohort = pd.Series(x).groupby(ii).mean()
streak = mx = 0
for v in cohort.values:
    streak = streak + 1 if v < 0 else 0
    mx = max(mx, streak)
print("  %d 個月,月勝率 %.0f%%,平均每月 %+.2f%%,中位 %+.2f%%,最差月 %+.2f%%,最好月 %+.2f%%,最長連輸 %d 個月" % (
    len(cohort), (cohort > 0).mean() * 100, cohort.mean() * 100, cohort.median() * 100, cohort.min() * 100, cohort.max() * 100, mx))
print("  每月:" + " ".join("%s %+.1f" % (dates[i][2:7], v * 100) for i, v in cohort.items()))

print("\n[J 爆量突破(每天都可能觸發,不限營收公告日)]")
avg20p = vyi.shift(1).rolling(20, min_periods=15).mean()
mx60 = close.shift(1).rolling(60, min_periods=50).max()
mn60 = close.shift(1).rolling(60, min_periods=50).min()
mx250 = close.shift(1).rolling(250, min_periods=200).max()
bo = radar.first((vyi >= 5 * avg20p) & (chg >= 5) & (vyi >= 0.3) & (close >= mx60) & (mx60 / mn60 - 1 <= 0.35) & (close >= mx250)).values
yoy3 = daily(rp["yoy3"])
all_days = [i for i in range(N) if START <= dates[i] <= END]
for lab, cond in (("爆量突破", bo), ("爆量突破 + 3 月營收年增 ≥ 20%", bo & (yoy3 >= 20)), ("爆量突破但營收衰退", bo & (yoy3 < 0))):
    line(lab, cond, rows=all_days, by_day=True)
bh = {}
for i in all_days:
    bh.setdefault(dates[i][:4], []).append(i)
for k, rows in sorted(bh.items()):
    line("爆量突破 + 營收成長 %s 年" % k, bo & (yoy3 >= 20), rows=rows, by_day=True)

print("\n[I 產業循環門檻敏感度](板塊等權指數,訊號後 60 日比所有板塊平均)")
import json  # noqa: E402
themes = [t for t in json.load(open(radar.history.ROOT + "/data/sectors/themes.json", encoding="utf-8"))]
ret = close.pct_change()
mx250c = close.rolling(250, min_periods=200).max()
IDX, BR, RV, RACC, RB = {}, {}, {}, {}, {}
for t in themes:
    mem = [c for c in t["codes"] if c in codes]
    if len(mem) < 3:
        continue
    IDX[t["id"]] = (1 + ret[mem].mean(axis=1).fillna(0)).cumprod()
    BR[t["id"]] = (close[mem] >= 0.95 * mx250c[mem]).sum(axis=1) / close[mem].notna().sum(axis=1)
    cur, prv = rp["rev"][mem], rp["rev"][mem].shift(12)
    both = cur.notna() & prv.notna()
    yy = (cur.where(both).sum(axis=1) / prv.where(both).sum(axis=1) - 1) * 100
    yy[both.sum(axis=1) < max(2, len(mem) // 2)] = np.nan
    y3_ = yy.rolling(3).mean()
    RV[t["id"]] = radar.to_daily(y3_.to_frame("x"), months, close.index)["x"]
    RACC[t["id"]] = radar.to_daily((y3_ - y3_.shift(3)).to_frame("x"), months, close.index)["x"]
    RB[t["id"]] = radar.to_daily(((rp["yoy"][mem] >= 20).sum(axis=1) / rp["yoy"][mem].notna().sum(axis=1)).to_frame("x"), months, close.index)["x"]
IDX, BR, RV, RACC, RB = map(pd.DataFrame, (IDX, BR, RV, RACC, RB))
fwd = IDX.shift(-60) / IDX.shift(-1) - 1
rel = fwd.sub(fwd.mean(axis=1), axis=0)
win_rows = pd.Series([START <= d <= END for d in dates], index=close.index)
rally = (BR >= 0.5) & (IDX >= IDX.rolling(250, min_periods=200).max())


def cyc(label, m):
    m = radar.first(m, 60) & win_rows.values[:, None]
    v = rel[m].stack().dropna()
    if len(v) < 5:
        print("  %-40s 樣本不足(n=%d)" % (label, len(v)))
        return
    print("  %-40s n=%3d  比其他板塊 %+6.1f%%  中位 %+6.1f%%  勝率 %3.0f%%" % (label, len(v), v.mean() * 100, v.median() * 100, (v > 0).mean() * 100))


for lv in (10, 15, 25):
    for ac in (5, 10, 20):
        cyc("營收轉強:年增≥%d、加速≥%d、廣度≥50%%" % (lv, ac), (RV >= lv) & (RACC >= ac) & (RB >= 0.5))
cyc("齊漲", rally)
for lv in (10, 15, 25):
    up = ((RV >= lv) & (RACC >= 10) & (RB >= 0.5)).rolling(60, min_periods=1).max().astype(bool)
    cyc("營收轉強(年增≥%d)+ 齊漲" % lv, up & rally)
