"""Sprint 004：把 PRD 核准版的短線規則（10 日「適合進場／中性／不建議」）拿 2011–2018 考一次。

規則與統計一律 import 現成定義（final.py 的 short_good／short_bad、entry_backtest.py 的 stat），本檔不定義規則、不調參數。
比較：同一天「該級 vs 名單其他股」（PRD 的差）＋同一天「該級 vs 當天整份名單直接買」；進場、持有、成本都和 final.py 相同。
門檻與判定標準寫在 ../exam-2011-18.md，考前定好，考後不改。
用法：
  python exam_2011_18.py --control    對照：2024-01-01～2026-10-27 要對上 final-4.txt，對不上回傳 1，不准考
  python exam_2011_18.py [--stars 4]  考試（資料沒涵蓋 2011 以前就拒跑）
"""
import argparse
import sys

import numpy as np
import pandas as pd

import combo
from entry_backtest import COST, LOSS, nw_t, stat
from final import short_bad, short_good

H = 10
EXAM = ("2011-01-01", "2018-12-31", None)
CONTROL = ("2024-01-01", "2026-10-27", "2026-10-27")
# final-4.txt「短線 持有 10 日」樣本外（n, 段, 平均, 差）；雲端資料起點較早，容許 ewm 起始值造成的微小差
EXPECT = {"適合進場": (5861, 1410, 1.90, 1.33), "不建議": (13581, 2027, -0.10, -1.65), "中性": (18202, 2333, 1.03, 0.70)}
TOL_N, TOL_PCT = 0.005, 0.05
_load = combo.load


def truncate(X, asof):
    """只留 asof（含）以前的資料，讓對照和 final-4.txt 用同一段期間。"""
    cut = lambda d: d[pd.to_datetime(d.index) <= pd.Timestamp(asof)]  # noqa: E731
    return {k: ({a: cut(b) for a, b in v.items()} if k == "D" else cut(v) if isinstance(v, (pd.DataFrame, pd.Series)) else v)
            for k, v in X.items()}


def fmt(s):
    return "n=%d 段=%d 平均 %+.2f%% 中位 %+.2f%% 勝率 %.1f%% 大跌 %.1f%%" % (s["n"], s["ep"], s["avg"], s["med"], s["win"], s["loss"])


def run(start, end, asof, stars_min):
    combo.load = (lambda: truncate(_load(), asof)) if asof else _load
    X, univ, R, _ = combo.prep(stars_min)
    pub_i = X["pub_i"]
    c, o = X["close"], X["open"]
    idx = pd.to_datetime(c.index)
    if idx[0] > pd.Timestamp(start) - pd.DateOffset(days=300) or idx[-1] < pd.Timestamp(end):
        sys.exit("資料 %s～%s 不夠涵蓋 %s～%s（含年線暖機），拒跑" % (c.index[0], c.index[-1], start, end))
    mk = lambda b: pd.DataFrame(np.repeat(b[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)  # noqa: E731
    ep = mk(pub_i.fillna(-1).values)
    fwd = c.shift(-H) / o.shift(-1) - 1 - COST
    mkt = fwd.where((X["vyi"] >= 0.3) & fwd.notna()).mean(axis=1)
    in_win = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    years = idx.year.values
    good, bad = short_good(R), short_bad(R)
    tiers = {"適合進場": good, "不建議": bad, "中性": ~good & ~bad}
    print("短線 10 日考試（%d 星以上；%s～%s；成本 %.3f%%；資料 %s～%s）" % (stars_min, start, end, COST * 100, c.index[0], c.index[-1]))
    print("差其他＝同一天「該級 vs 名單其他股」；差全買＝同一天「該級 vs 當天整份名單直接買」；百分點，t＝Newey-West（lag=10）")
    ok = mk(in_win)
    base = stat(univ, univ & False, fwd, mkt, ep, ok, H, LOSS[H])
    print("\n當天直接買（整份名單不看標籤）\n    " + fmt(base))
    all_day = fwd.where(univ & ok & fwd.notna()).mean(axis=1)
    got = {}
    for name, m in tiers.items():
        sel, other = univ & m, univ & ~m
        s = stat(sel, other, fwd, mkt, ep, ok, H, LOSS[H])
        got[name] = s
        if not s.get("n"):
            print("\n%s\n    無樣本" % name)
            continue
        d = (fwd.where(sel & ok & fwd.notna()).mean(axis=1) - all_day).dropna()
        yr = []
        for y in sorted(set(years[in_win])):
            r = stat(sel, other, fwd, mkt, ep, mk(in_win & (years == y)), H, LOSS[H])
            if r.get("n") and r.get("diff") is not None:
                yr.append("%d 差 %+.2f（n=%d）" % (y, r["diff"], r["n"]))
        print("\n%s\n    %s\n    差其他 %+.2f t=%s；差全買 %+.2f t=%.2f\n    逐年：%s" % (
            name, fmt(s), s["diff"] or 0, s["t"], float(d.mean()) * 100, float(nw_t(d.values, H)), "；".join(yr)))
    print("\n逐年資料覆蓋（名單天數／平均每日檔數／名單內法人有值比例，2012-05 前沒有法人資料，星等少扣 1★）")
    fo = X["fo"].notna() & (X["fo"] != 0)
    for y in sorted(set(years[in_win])):
        b = in_win & (years == y)
        n = univ.values[b].sum(axis=1)
        print("  %d：%d 天／%.1f 檔／%.1f%%" % (y, (n > 0).sum(), n[n > 0].mean() if (n > 0).any() else 0,
                                          fo.values[b][univ.values[b]].mean() * 100 if n.sum() else 0))
    return got


def check(got):
    bad = []
    for k, (n, e, a, d) in EXPECT.items():
        s = got[k]
        if abs(s["n"] - n) > n * TOL_N or abs(s["ep"] - e) > e * TOL_N or abs(s["avg"] - a) > TOL_PCT or abs(s["diff"] - d) > TOL_PCT:
            bad.append("%s 預期 n=%d 段=%d 平均 %+.2f 差 %+.2f，實得 n=%d 段=%d 平均 %+.2f 差 %+.2f" % (k, n, e, a, d, s["n"], s["ep"], s["avg"], s["diff"]))
    print("\n對照結果：" + ("吻合 final-4.txt" if not bad else "不吻合\n  " + "\n  ".join(bad)))
    return not bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--stars", type=int, default=4)
    a = ap.parse_args()
    res = run(*(CONTROL if a.control else EXAM), a.stars)
    if a.control and not check(res):
        sys.exit(1)
