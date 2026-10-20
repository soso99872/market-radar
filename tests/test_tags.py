"""scripts/radar.py condition_tags 測試:小型固定資料,每個標籤測「剛好達標／剛好不達標」。
判定日 T = 最後一列。每個測試只造一檔股票(或同標籤的一對 A/B),其餘標籤不管。"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import radar  # noqa: E402


def panel(n, cols):
    """n 個交易日、cols = {代號: 長度 n 的序列} 的 DataFrame。"""
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({k: np.asarray(v, dtype=float) for k, v in cols.items()}, index=idx)


def tags(close=None, value=None, yoy=None, yoy3=None, net=None, topic=None, lag=None, n=None):
    ref = next(x for x in (close, value, yoy, yoy3, net) if x is not None)
    z = pd.DataFrame(np.nan, index=ref.index, columns=ref.columns)
    return radar.condition_tags(*(z if x is None else x for x in (close, value, yoy, yoy3, net)), ref.index[-1], topic, lag)


class VolUp(unittest.TestCase):
    # t-24..t-5 共 20 日均額 10;近 5 日均額 15 → 比值剛好 1.5 達標;14.9 不達標
    def test_edge(self):
        for last5, want in ((15.0, True), (14.9, False)):
            v = panel(30, {"A": [10] * 25 + [last5] * 5})
            self.assertEqual("vol_up" in tags(value=v).get("A", []), want, last5)

    def test_not_enough_days(self):   # 只有 24 日,t-24 不存在 → 不給
        v = panel(24, {"A": [10] * 19 + [100] * 5})
        self.assertNotIn("A", tags(value=v))


class MaUp(unittest.TestCase):
    # 60 日收盤:前 55 日 100,之後 5 日 X。MA60 = (55*100+5X)/60;MA20 = (15*100+5X)/20
    # X=130:MA20=107.5、MA60≈102.5、收盤130 → 排列成立;5 日前(t-5)的 MA20 = 100(15 日前全 100 → 窗內全 100)→ 上升
    def test_edge(self):
        up = panel(60, {"A": [100] * 55 + [130] * 5})
        self.assertIn("ma_up", tags(close=up)["A"])

    def test_close_below_ma20(self):   # 最後一日跌回 100:MA20 = (15*100+4*130+100)/20 = 106 > 收盤 100 → 不給
        c = panel(60, {"A": [100] * 55 + [130] * 4 + [100]})
        self.assertNotIn("A", tags(close=c))

    def test_flat(self):   # 全 100:收盤 = MA20 = MA60,不是「>」→ 不給
        self.assertNotIn("A", tags(close=panel(60, {"A": [100] * 60})))

    def test_close_equals_ma20(self):
        # 前 40 日 200、後 20 日 150:T 收盤 150 = MA20(150),不是「>」→ 不給
        self.assertNotIn("A", tags(close=panel(60, {"A": [200] * 40 + [150] * 20})))

    def test_ma20_vs_5d_ago_edge(self):
        # 序列(60 日):35 日 80、5 日 120、15 日 100、最後 5 日 X。
        # MA20(T) = (15*100 + 5X)/20;MA20(T-5)(窗 t-24..t-5)= (5*120 + 15*100)/20 = 105
        # X=120:MA20(T)=105,等於 5 日前 → 不給;X=121:105.25 > 105 → 給
        # 收盤 X > MA20(T)、MA60(T) = (35*80 + 600 + 1500 + 5X)/60 ≈ 91.7 < MA20,排列條件兩者皆成立
        for x, want in ((120, False), (121, True)):
            c = panel(60, {"A": [80] * 35 + [120] * 5 + [100] * 15 + [x] * 5})
            self.assertEqual("ma_up" in tags(close=c).get("A", []), want, x)


class NearHigh(unittest.TestCase):
    # 250 日:一天收 100,其餘 95 → 最後收 95 = 100*0.95 剛好達標;94.99 不達標
    def test_edge(self):
        for last, want in ((95.0, True), (94.99, False)):
            c = panel(250, {"A": [100] + [90] * 248 + [last]})
            self.assertEqual("near_high" in tags(close=c).get("A", []), want, last)

    def test_window_250(self):   # 251 日:最高 100 在第 0 天,已出窗(窗 = 最後 250 日)→ 最高變 90,收 90 達標
        c = panel(251, {"A": [100] + [90] * 250})
        self.assertIn("near_high", tags(close=c)["A"])

    def test_short(self):   # 不滿 200 日不給
        self.assertNotIn("A", tags(close=panel(199, {"A": [100] * 199})))


class RevMom(unittest.TestCase):
    # 最新年增與近 3 月平均年增都 ≥ 20 才給
    def test_edge(self):
        for y, y3, want in ((20, 20, True), (19.9, 25, False), (25, 19.9, False)):
            r = tags(yoy=panel(3, {"A": [y] * 3}), yoy3=panel(3, {"A": [y3] * 3}))
            self.assertEqual("rev_mom" in r.get("A", []), want, (y, y3))

    def test_missing(self):
        self.assertNotIn("A", tags(yoy=panel(3, {"A": [np.nan] * 3}), yoy3=panel(3, {"A": [30] * 3})))


class Chips(unittest.TestCase):
    # 近 20 日累計 > 0 且近 5 日累計 > 0
    def test_edge(self):
        # 前 15 日 -1(共 -15),後 5 日 +3(共 +15) → 20 日累計 0,不 > 0 → 不給
        self.assertNotIn("A", tags(net=panel(30, {"A": [0] * 10 + [-1] * 15 + [3] * 5})))
        # 後 5 日 +3.2(共 16) → 20 日累計 +1 > 0、5 日累計 16 > 0 → 給
        self.assertIn("chips", tags(net=panel(30, {"A": [0] * 10 + [-1] * 15 + [3.2] * 5}))["A"])

    def test_5d_zero(self):   # 20 日 +,但近 5 日累計剛好 0(+1, +1, -1, -1, 0)→ 不給
        self.assertNotIn("A", tags(net=panel(30, {"A": [1] * 25 + [1, 1, -1, -1, 0]})))

    def test_short(self):   # 只有 19 日資料 → 不給
        self.assertNotIn("A", tags(net=panel(19, {"A": [1] * 19})))


class TopicAndLaggard(unittest.TestCase):
    def setUp(self):
        self.c = panel(3, {"A": [1, 1, 1], "B": [1, 1, 1]})

    def test_topic_sync(self):
        self.assertEqual({"A": ["topic_sync"]}, tags(close=self.c, topic={"A"}, lag=set()))
        self.assertEqual({}, tags(close=self.c, topic=set(), lag=set()))   # 沒有觸發題材

    def test_laggard(self):
        self.assertEqual({"B": ["laggard"]}, tags(close=self.c, topic=set(), lag={"B"}))

    def test_laggard_failed(self):   # laggard 失敗(None):兩個標籤都不給
        self.assertEqual({}, tags(close=self.c))

    def test_order_and_unknown_code(self):   # 順序依表;不在面板的代號略過
        r = tags(close=self.c, topic={"A", "ZZ"}, lag={"A"})
        self.assertEqual({"A": ["topic_sync", "laggard"]}, r)


class Defs(unittest.TestCase):
    def test_defs_cover_order(self):
        self.assertEqual(set(radar.TAG_ORDER), set(radar.TAG_DEFS))
        for d in radar.TAG_DEFS.values():
            self.assertTrue(d["name"] and d["desc"])


if __name__ == "__main__":
    unittest.main()
