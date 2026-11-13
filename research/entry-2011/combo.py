"""Sprint 004：把單一規則組成「適合進場／中性／不建議」三組，並驗證「等回檔」是否真的比今天買好。

候選組合只用樣本內（entry_backtest.py 的樣本內 t 值）挑選，樣本外只用來驗證，不回頭調參數。
用法：python combo.py [--stars 4] > combo-<stars>.txt
"""
import argparse
import sys

import numpy as np
import pandas as pd

from entry_backtest import COST, LOSS, SPLIT, features, ma
from load import load, radar_members


def prep(stars_min):
    X = load()
    member, stars = radar_members(X)
    c = X["close"]
    pub_i = X["pub_i"]
    X["pub_days"] = pd.DataFrame(np.repeat((np.arange(len(c)) - pub_i.values)[:, None], c.shape[1], axis=1),
                                 index=c.index, columns=c.columns)
    R = features(X)
    m60, m240 = ma(c, 60), ma(c, 240)
    R["_b60"] = c / m60 - 1
    return X, member & (stars >= stars_min), R, pub_i


# 候選組合（名稱 → 函式(R) → 布林矩陣）：從樣本內加分／扣分的單一規則挑趨勢類組 3 種，再比樣本內差距選一種（見 PRD 2.3）
SHORT = {
    "短線適合 A：均線多頭排列＋（創 20 日新高或站上布林上軌）":
        lambda R: R["均線多頭排列（收>20>60>240 日均）"] & (R["創 20 日新高"] | R["布林上軌之上"]),
    "短線適合 B：短均線多頭＋距 52 週高點 3% 內":
        lambda R: R["短均線多頭（5>10>20 日均）"] & R["距 52 週高點 3% 內"],
    "短線適合 C：均線多頭排列＋短均線多頭":
        lambda R: R["均線多頭排列（收>20>60>240 日均）"] & R["短均線多頭（5>10>20 日均）"],
    "短線不建議 A：跌破季線或 RSI14<40":
        lambda R: R["跌破季線（收<60 日均）"] | R["RSI14 <40"],
    "短線不建議 B：跌破季線或 KD 低檔金叉或乖離季線 ≤15% 且短均線非多頭":
        lambda R: R["跌破季線（收<60 日均）"] | R["KD 低檔黃金交叉（K<30 上穿 D）"] | (R["乖離季線 ≤15%"] & ~R["短均線多頭（5>10>20 日均）"]),
}
LONG = {
    "長線適合 A：均線多頭排列＋短均線多頭":
        lambda R: R["均線多頭排列（收>20>60>240 日均）"] & R["短均線多頭（5>10>20 日均）"],
    "長線適合 B：Minervini 趨勢模板＋短均線多頭":
        lambda R: R["Minervini 趨勢模板"] & R["短均線多頭（5>10>20 日均）"],
    "長線適合 C：均線多頭排列＋創 20 日新高":
        lambda R: R["均線多頭排列（收>20>60>240 日均）"] & R["創 20 日新高"],
    "長線不建議 A：跌破年線或跌破季線或 RSI14<40":
        lambda R: R["跌破年線（收<240 日均）"] | R["跌破季線（收<60 日均）"] | R["RSI14 <40"],
    "長線不建議 B：跌破年線":
        lambda R: R["跌破年線（收<240 日均）"],
}


def tier_stats(mask, fwd, mkt, ok, ep, h):
    s = mask & ok & fwd.notna()
    n = int(s.values.sum())
    if not n:
        return {"n": 0}
    f = fwd.values[s.values]
    e = fwd.sub(mkt, axis=0).values[s.values]
    eps = len(set(zip(np.where(s.values)[1], ep.values[s.values])))
    return {"n": n, "ep": eps, "avg": f.mean() * 100, "med": np.median(f) * 100, "exc": np.nanmean(e) * 100,
            "win": (f > 0).mean() * 100, "loss": (f < LOSS[h]).mean() * 100}


def fmt(st):
    if not st.get("n"):
        return "無樣本"
    return "n=%d 段=%d 平均 %+.2f%% 中位 %+.2f%% 超額 %+.2f%% 勝率 %.1f%% 大跌 %.1f%%" % (
        st["n"], st["ep"], st["avg"], st["med"], st["exc"], st["win"], st["loss"])


def run(stars_min):
    X, univ, R, pub_i = prep(stars_min)
    c, o = X["close"], X["open"]
    idx = pd.to_datetime(c.index)
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    pos = np.arange(len(c))
    ep = pd.DataFrame(np.repeat(pub_i.fillna(-1).values[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)
    entry = o.shift(-1)
    tradable = X["vyi"] >= 0.3
    years = idx.year.values
    print("組合回測（%d 星以上；樣本外自 %s；成本 %.3f%%）" % (stars_min, SPLIT, COST * 100))
    for kind, combos, hs in (("短線", SHORT, (5, 10, 20)), ("長線", LONG, (60, 120))):
        for h in hs:
            fwd = c.shift(-h) / entry - 1 - COST
            mkt = fwd.where(tradable & fwd.notna()).mean(axis=1)
            mk = lambda b: pd.DataFrame(np.repeat(b[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)  # noqa: E731
            is_ok, oos_ok = mk(pos + h < split_i), mk(pos >= split_i)
            print("\n== %s 持有 %d 日 ==" % (kind, h))
            for nm, ok in (("樣本內", is_ok), ("樣本外", oos_ok)):
                print("  名單全部 %s：%s" % (nm, fmt(tier_stats(univ, fwd, mkt, ok, ep, h))))
            for name, fn in combos.items():
                m = univ & fn(R)
                print("  " + name)
                for nm, ok in (("樣本內", is_ok), ("樣本外", oos_ok)):
                    print("    %s 符合：%s" % (nm, fmt(tier_stats(m, fwd, mkt, ok, ep, h))))
                    print("    %s 其他：%s" % (nm, fmt(tier_stats(univ & ~fn(R), fwd, mkt, ok, ep, h))))
                yr = []
                for y in sorted(set(years[split_i:])):
                    st = tier_stats(m, fwd, mkt, oos_ok & mk(years == y), ep, h)
                    so = tier_stats(univ & ~fn(R), fwd, mkt, oos_ok & mk(years == y), ep, h)
                    if st.get("n") and so.get("n"):
                        yr.append("%d：%+.2f vs %+.2f（n=%d）" % (y, st["avg"], so["avg"], st["n"]))
                print("    樣本外逐年平均（符合 vs 其他）：" + "；".join(yr))
    wait_test(X, univ, R, split_i)


def wait_test(X, univ, R, split_i):
    """「等回檔」：今天位置偏高（乖離季線 > 門檻）時，等最多 W 天回到條件內再買，跟今天就買比，
    兩版並列：①同一天（t+h）出場 ②等回檔也持有 h 天；等不到就在 t+W+1 開盤買（強迫進場，避免只挑有回檔的樣本）。
    樣本內／外只看 t+h 是否早於切點；②最晚到 t+h+W 才出場，少數樣本會跨進樣本外幾天，影響很小、結論不變。"""
    c, o = X["close"].values, X["open"].values
    b60 = R["_b60"].values
    m20 = ma(X["close"], 20).values
    U = univ.values
    N = len(c)
    print("\n== 等回檔測試（今天買 vs 等回檔再買，兩版：同日出場／同樣持有 h 天；等不到就第 W+1 天買）==")
    for kind, h, W in (("短線", 10, 5), ("短線", 20, 10), ("長線", 60, 20), ("長線", 120, 20)):
        for thr in (0.25, 0.40):
            for trig_name in ("回到 20 日均線（收 ≤ 20 日均×1.02）", "乖離季線降到 15% 以下"):
                res = {"is": [], "oos": []}
                hit = {"is": [], "oos": []}
                ii, jj = np.where(U & (b60 > thr))
                for i, j in zip(ii, jj):
                    if i + h >= N or i + 1 >= N or np.isnan(o[i + 1, j]) or np.isnan(c[i + h, j]):
                        continue
                    seg = "oos" if i >= split_i else ("is" if i + h < split_i else None)
                    if seg is None:
                        continue
                    now = c[i + h, j] / o[i + 1, j] - 1
                    k = None
                    for s in range(i + 1, min(i + W, N - 2) + 1):
                        trig = (c[s, j] <= m20[s, j] * 1.02) if trig_name.startswith("回到") else (b60[s, j] <= 0.15)
                        if trig:
                            k = s
                            break
                    buy_i = (k if k is not None else i + W) + 1
                    if buy_i >= i + h or np.isnan(o[buy_i, j]):
                        continue
                    later = c[i + h, j] / o[buy_i, j] - 1
                    out_eq = buy_i + h - 1   # 等回檔也持有 h 天（主管 2026-10-28：同日出場會讓等回檔少抱幾天）
                    if out_eq >= N or np.isnan(c[out_eq, j]):
                        continue
                    later_eq = c[out_eq, j] / o[buy_i, j] - 1
                    res[seg].append((now, later, later_eq, buy_i - i - 1))
                    hit[seg].append(k is not None)
                for seg in ("is", "oos"):
                    a = np.array(res[seg])
                    if not len(a):
                        continue
                    d = a[:, 1] - a[:, 0]
                    d2 = a[:, 2] - a[:, 0]
                    print("  %s h=%d 等≤%d 天｜乖離季線>%d%%｜%s｜%s n=%d 等到回檔 %.0f%% 平均等 %.1f 天｜今天買 %+.2f%%"
                          "｜同日出場：等回檔 %+.2f%% 差 %+.2f%%（等比較好 %.0f%%）｜同樣持有 %d 天：等回檔 %+.2f%% 差 %+.2f%%（等比較好 %.0f%%）" % (
                        kind, h, W, thr * 100, trig_name, "樣本內" if seg == "is" else "樣本外", len(a), np.mean(hit[seg]) * 100,
                        a[:, 3].mean(), a[:, 0].mean() * 100, a[:, 1].mean() * 100, d.mean() * 100, (d > 0).mean() * 100,
                        h, a[:, 2].mean() * 100, d2.mean() * 100, (d2 > 0).mean() * 100))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stars", type=int, default=4)
    run(ap.parse_args().stars)
