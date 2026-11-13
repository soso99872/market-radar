"""Sprint 004：PRD 採用的最終分級（短線 10 日、長線 60／120 日），算樣本內外的統計、同日配對差與 Newey-West t 值，
以及最後一天名單的分級分布。規則只用樣本內結果挑，樣本外只驗證。
用法：python final.py [--stars 4] > final-<stars>.txt
"""
import argparse

import numpy as np
import pandas as pd

from combo import prep
from entry_backtest import COST, LOSS, SPLIT, stat


def short_bad(R):
    return R["跌破季線（收<60 日均）"] | R["KD 低檔黃金交叉（K<30 上穿 D）"] | (R["乖離季線 ≤15%"] & ~R["短均線多頭（5>10>20 日均）"])


def short_good(R):
    return R["均線多頭排列（收>20>60>240 日均）"] & (R["創 20 日新高"] | R["布林上軌之上"]) & ~short_bad(R)


def long_bad(R):
    return R["跌破年線（收<240 日均）"] | R["跌破季線（收<60 日均）"] | R["RSI14 <40"]


TIERS = {
    "短線": ((5, 10, 20), {"適合進場": short_good, "不建議": short_bad,
                          "中性": lambda R: ~short_good(R) & ~short_bad(R)}),
    "長線": ((60, 120), {"不建議": long_bad, "未見扣分（其他）": lambda R: ~long_bad(R),
                        "其中跌破年線": lambda R: R["跌破年線（收<240 日均）"]}),
}


def run(stars_min):
    X, univ, R, pub_i = prep(stars_min)
    c, o = X["close"], X["open"]
    idx = pd.to_datetime(c.index)
    split_i = int(idx.searchsorted(pd.Timestamp(SPLIT)))
    pos = np.arange(len(c))
    ep = pd.DataFrame(np.repeat(pub_i.fillna(-1).values[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)
    entry = o.shift(-1)
    tradable = X["vyi"] >= 0.3
    mk = lambda b: pd.DataFrame(np.repeat(b[:, None], c.shape[1], axis=1), index=c.index, columns=c.columns)  # noqa: E731
    years = idx.year.values
    print("最終分級回測（%d 星以上；樣本外自 %s；成本 %.3f%%；資料到 %s）" % (stars_min, SPLIT, COST * 100, c.index[-1]))
    print("差＝同一天「該級 vs 名單其他股」平均報酬差（百分點），t＝Newey-West（lag=持有天數）")
    for kind, (hs, tiers) in TIERS.items():
        for h in hs:
            fwd = c.shift(-h) / entry - 1 - COST
            mkt = fwd.where(tradable & fwd.notna()).mean(axis=1)
            print("\n== %s 持有 %d 日 ==" % (kind, h))
            for name, fn in tiers.items():
                m = univ & fn(R)
                other = univ & ~fn(R)
                line = []
                for nm, ok in (("樣本內", mk(pos + h < split_i)), ("樣本外", mk(pos >= split_i))):
                    s = stat(m, other, fwd, mkt, ep, ok, h, LOSS[h])
                    if not s.get("n"):
                        line.append("%s 無樣本" % nm)
                        continue
                    line.append("%s n=%d 段=%d 平均 %+.2f%% 中位 %+.2f%% 勝率 %.1f%% 大跌 %.1f%% 差 %+.2f t=%s" % (
                        nm, s["n"], s["ep"], s["avg"], s["med"], s["win"], s["loss"], s["diff"] or 0, s["t"]))
                yr = []
                for y in sorted(set(years[split_i:])):
                    s = stat(m, other, fwd, mkt, ep, mk((pos >= split_i) & (years == y)), h, LOSS[h])
                    if s.get("n") and s.get("diff") is not None:
                        yr.append("%d 差 %+.2f（n=%d）" % (y, s["diff"], s["n"]))
                print("  %s\n    %s\n    %s\n    樣本外逐年：%s" % (name, line[0], line[1], "；".join(yr)))
    last = univ.iloc[-1]
    print("\n== 最後一天（%s）名單 %d 檔的分級 ==" % (c.index[-1], int(last.sum())))
    for kind, (_, tiers) in TIERS.items():
        print("  %s：%s" % (kind, "、".join("%s %d" % (k, int((last & fn(R).iloc[-1]).sum())) for k, fn in tiers.items())))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stars", type=int, default=4)
    run(ap.parse_args().stars)
