"""scripts/laggard.py 規則測試:手工建的小型固定資料,不讀 data/。

共用情境(alpha 題材,判定日 T = 2026-03-11,T 前 20 個交易日收盤皆 100):
  代號 發動 年增(2月) 收盤T   近20日漲幅
  L1   是   100       130(新高)  +0.30
  L2   是   80        120(新高)  +0.20
  P1   否   90        105        +0.05   <- 應入選
  P2   否   20        100        0.00    年增低於中位數
  P3   否   88        115        +0.15   漲幅高於中位數
  P4   否   85        101        +0.01   列為處置股時排除
  P5   否   50        98         -0.02   年增低於中位數
  P6   否   95        110        +0.10   漲幅等於中位數
  P7   否   40        110        +0.10   年增低於中位數
  年增排序 20,40,50,80,85,88,90,95,100 → 中位數(第 5 個) 85
  漲幅排序 -.02,0,.01,.05,.10,.10,.15,.20,.30 → 中位數(第 5 個) 0.10
  非發動股在 T 前 100 個交易日有一天收 300,所以 T 當天不會創 52 週新高。
beta 題材:B1 發動,B2~B4 不發動 → 只有 1 檔發動,不觸發。
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import laggard  # noqa: E402

DATES = pd.bdate_range("2025-01-01", "2026-04-30")
TOPICS = {"alpha": ["L1", "L2", "P1", "P2", "P3", "P4", "P5", "P6", "P7"],
          "beta": ["B1", "B2", "B3", "B4"]}
# 代號: (T 日收盤相對 100 的漲幅, 是否發動)
SPEC = {"L1": (0.30, True), "L2": (0.20, True), "P1": (0.05, False), "P2": (0.00, False),
        "P3": (0.15, False), "P4": (0.01, False), "P5": (-0.02, False), "P6": (0.10, False),
        "P7": (0.10, False), "B1": (0.25, True), "B2": (0.02, False), "B3": (0.03, False), "B4": (0.01, False)}
YOY_A = {"L1": 100, "L2": 80, "P1": 90, "P2": 20, "P3": 88, "P4": 85, "P5": 50, "P6": 95, "P7": 40,
         "B1": 100, "B2": 90, "B3": 95, "B4": 80}
YOY_B = dict(YOY_A, P1=20, P2=90)           # 1 月營收:P1、P2 的年增對調(中位數不變)
YOY_C = {c: -50.0 for c in YOY_A}           # 3 月營收(4/11 才公告):若被誤用會全部排除

T = "2026-03-11"      # 2 月營收從 3/11 起可用


def make(day, seed=None):
    """建立 day 當天的價格面板。seed 不為 None 時,day 之後的收盤、成交額、漲幅改成亂數。"""
    t = DATES.get_loc(pd.Timestamp(day))
    close = pd.DataFrame(100.0, index=DATES, columns=list(SPEC))
    value = pd.DataFrame(1.0, index=DATES, columns=list(SPEC))
    chg = pd.DataFrame(0.0, index=DATES, columns=list(SPEC))
    for c, (r, launch) in SPEC.items():
        if not launch:
            close.iloc[t - 100, close.columns.get_loc(c)] = 300.0   # 前 250 日內有過 300 的高點
        close.iloc[t, close.columns.get_loc(c)] = 100.0 * (1 + r)
    if seed is not None:
        rng = np.random.RandomState(seed)
        n = len(DATES) - t - 1
        close.iloc[t + 1:] = rng.uniform(1, 1000, (n, close.shape[1]))
        value.iloc[t + 1:] = rng.uniform(0, 100, (n, close.shape[1]))
        chg.iloc[t + 1:] = rng.uniform(-10, 10, (n, close.shape[1]))
    return close, value, chg


def yoy_table(c_row=YOY_C):
    rows = {(2026, 1): YOY_B, (2026, 2): YOY_A, (2026, 3): c_row}
    idx = pd.MultiIndex.from_tuples(list(rows))
    return pd.DataFrame([[float(rows[k][c]) for c in SPEC] for k in rows], index=idx, columns=list(SPEC))


def run(day, restricted=(), yoy=None, seed=None):
    close, value, chg = make(day, seed)
    L = laggard.launches(close, value, chg)
    out = laggard.select(pd.Timestamp(day), close, L, yoy_table() if yoy is None else yoy, TOPICS, restricted)
    return L, out


class LaunchTest(unittest.TestCase):
    def test_high52_launch(self):
        # L1 收 130 > 前 250 日最高 100 → 發動;P1 前面有 300 → 不發動
        L, _ = run(T)
        row = L.loc[T]
        self.assertTrue(row["L1"] and row["L2"] and row["B1"])
        self.assertFalse(row[["P1", "P2", "P3", "P4", "P5", "P6", "P7", "B2"]].any())

    def test_breakout_and_no_dedupe(self):
        # X:成交額 1 億持平,第 t 天 6 億、漲 6%(100→106):前 20 日均 1 億,6 ≥ 5×1;區間 0% ≤ 35%;106 ≥ 前高 100 → 發動。
        #    第 t+1 天 10 億、漲 6.6%(106→113):前 20 日均 (19×1+6)/20=1.25,5×1.25=6.25 ≤ 10 → 連續第二天仍發動(不去重)。
        # Y:收盤等於前高 100(非新高)但爆量漲 5% → 只有爆量突破這條路成立。
        # Z:爆量但成交額 0.1 億 < 0.3 億門檻 → 不發動。
        cols = ["X", "Y", "Z"]
        close = pd.DataFrame(100.0, index=DATES, columns=cols)
        value = pd.DataFrame(1.0, index=DATES, columns=cols)
        chg = pd.DataFrame(0.0, index=DATES, columns=cols)
        t = 300
        close.iloc[t, 0], close.iloc[t + 1, 0] = 106.0, 113.0
        value.iloc[t, 0], value.iloc[t + 1, 0] = 6.0, 10.0
        chg.iloc[t, 0], chg.iloc[t + 1, 0] = 6.0, 6.6
        value.iloc[t, 1], chg.iloc[t, 1] = 6.0, 5.0
        value.iloc[:, 2] = 0.01
        value.iloc[t, 2], chg.iloc[t, 2] = 0.1, 6.0
        L = laggard.launches(close, value, chg)
        self.assertTrue(L.iloc[t, 0] and L.iloc[t + 1, 0])
        self.assertTrue(L.iloc[t, 1])
        self.assertFalse(L.iloc[t, 2])
        self.assertFalse(L.iloc[t - 1].any())


class SelectTest(unittest.TestCase):
    def test_1_not_enough_launchers(self):
        # beta 只有 B1 發動(1 檔 < 2)→ 不觸發;B2~B4 即使年增高、漲幅低也不輸出
        L, out = run(T)
        trig = laggard.triggers(pd.Timestamp(T), L, TOPICS)
        self.assertEqual(trig, {"alpha": ["L1", "L2"]})
        self.assertFalse([x for x in out if x["topic"] == "beta"])

    def test_2_yoy_below_median(self):
        # 年增中位數 85:P2 為 20、P5 為 50、P7 為 40,皆 < 85 → 排除
        _, out = run(T)
        codes = [x["code"] for x in out]
        for c in ("P2", "P5", "P7"):
            self.assertNotIn(c, codes)

    def test_3_ret20_not_below_median(self):
        # 漲幅中位數 0.10:P3 為 0.15(高於)、P6 為 110/100-1=0.10(等於,要求 < 故排除);兩者年增 88、95 ≥ 85 本來合格
        _, out = run(T)
        codes = [x["code"] for x in out]
        self.assertNotIn("P3", codes)
        self.assertNotIn("P6", codes)

    def test_4_restricted(self):
        # P4 年增 85 ≥ 85、漲幅 0.01 < 0.10,本來入選;列為處置股後排除
        _, out = run(T)
        self.assertEqual(sorted(x["code"] for x in out), ["P1", "P4"])
        _, out = run(T, restricted={"P4"})
        self.assertEqual([x["code"] for x in out], ["P1"])

    def test_5_launchers_not_listed(self):
        # L1(年增 100 ≥ 85、但漲幅 0.30 本就高)、L2 是發動者,不列入。另測:發動者年增高、漲幅低時也不列入
        _, out = run(T)
        codes = [x["code"] for x in out]
        self.assertNotIn("L1", codes)
        self.assertNotIn("L2", codes)
        # 把 L1 的 T 日漲幅設成 0(收 100 不會創高)就不發動 → 觸發只剩 L2 一檔 → 整個 alpha 不觸發
        close, value, chg = make(T)
        close.loc[T, "L1"] = 100.0
        L = laggard.launches(close, value, chg)
        self.assertFalse(L.loc[T, "L1"])
        self.assertEqual(laggard.triggers(pd.Timestamp(T), L, TOPICS), {})

    def test_6_normal_selection(self):
        # 觸發 alpha(L1、L2);P1 年增 90 ≥ 85,漲幅 105/100-1=0.05 < 0.10 → 入選;P4 設為處置股排除
        _, out = run(T, restricted={"P4"})
        self.assertEqual(len(out), 1)
        x = out[0]
        self.assertEqual((x["code"], x["topic"], x["launched"]), ("P1", "alpha", ["L1", "L2"]))
        self.assertAlmostEqual(x["yoy"], 90.0)
        self.assertAlmostEqual(x["ret20"], 0.05)
        self.assertAlmostEqual(x["yoy_median"], 85.0)
        self.assertAlmostEqual(x["ret20_median"], 0.10)

    def test_7_no_lookahead(self):
        # T 之後的價格、成交額、漲幅改成亂數;T 尚未公告的 3 月營收(4/11 才可用)改成別的值 → 結果完全不變
        _, base = run(T)
        self.assertEqual(sorted(x["code"] for x in base), ["P1", "P4"])
        for seed in (1, 2, 3):
            rng = np.random.RandomState(seed)
            other = {c: float(rng.uniform(-100, 500)) for c in YOY_A}
            _, got = run(T, yoy=yoy_table(other), seed=seed)
            self.assertEqual(got, base)

    def test_8_revenue_release_boundary(self):
        # 1 月營收在 3/10 仍是最新(2 月營收 3/11 才可用):3/10 用 1 月 → P2 年增 90 入選、P1 年增 20 排除;3/11 用 2 月 → 相反
        _, a = run("2026-03-10")
        self.assertIn("P2", [x["code"] for x in a])
        self.assertNotIn("P1", [x["code"] for x in a])
        _, b = run("2026-03-11")
        self.assertIn("P1", [x["code"] for x in b])
        self.assertNotIn("P2", [x["code"] for x in b])

    def test_9_member_without_close_excluded_from_median(self):
        # N 在 alpha 題材,T 日收盤缺值(停牌)但有營收年增 999。
        # 不算 N:年增 9 檔中位數 85 → P4(85)與 P1(90)入選。
        # 若誤把 N 算進去:10 檔排序後第 5、6 個是 85、88 → 中位數 86.5,P4 年增 85 < 86.5 被排除。
        close, value, chg = make(T)
        for df in (close, value, chg):
            df["N"] = 100.0
        close.loc[T, "N"] = np.nan
        yoy = yoy_table()
        yoy["N"] = 999.0
        topics = {"alpha": TOPICS["alpha"] + ["N"], "beta": TOPICS["beta"]}
        L = laggard.launches(close, value, chg)
        out = laggard.select(pd.Timestamp(T), close, L, yoy, topics)
        self.assertEqual(sorted(x["code"] for x in out), ["P1", "P4"])
        self.assertAlmostEqual(out[0]["yoy_median"], 85.0)

    def test_10_day_not_in_index(self):
        close, value, chg = make(T)
        L = laggard.launches(close, value, chg)
        with self.assertRaises(KeyError):
            laggard.select(pd.Timestamp("2026-03-14"), close, L, yoy_table(), TOPICS)   # 週六

    def test_8_known_yoy_dates(self):
        y = yoy_table()
        self.assertTrue(laggard.known_yoy(y, "2026-02-10").empty)           # 1 月營收 2/11 才可用
        self.assertEqual(laggard.known_yoy(y, "2026-02-11")["P1"], 20.0)
        self.assertEqual(laggard.known_yoy(y, "2026-03-10")["P1"], 20.0)    # 2 月營收 3/10 還不可用
        self.assertEqual(laggard.known_yoy(y, "2026-03-11")["P1"], 90.0)    # 3/11 起可用
        self.assertEqual(laggard.known_yoy(y, "2026-04-10")["P1"], 90.0)    # 3 月營收 4/10 還不可用
        self.assertEqual(laggard.known_yoy(y, "2026-04-11")["P1"], -50.0)   # 4/11 起可用

BT_DATES = pd.bdate_range("2025-01-01", periods=450)


class BacktestTest(unittest.TestCase):
    """回測統計:alpha 題材 A、B 在 t、t+1 兩天都創新高(發動),C 是落後補漲股(年增 50 ≥ 中位數 10,20 日漲幅 0 < 中位數)。
    t = 第 300 個交易日。全部開盤 100、指數平盤 100,只有下面這些點不同:
      C 收盤:t+20 = 110、t+21 = 90,其餘 100;指數:t+20 = 104、t+21 = 102。
    樣本 1(訊號日 t,進場 t+1 開盤 100):
      20 日:出場 t+20 收盤 110 → 報酬 0.10 − 0.005425 = 0.094575;指數 104/100−1 = 0.04;超額 0.054575(贏、沒虧)
      60 日:出場 t+60 收盤 100 → 報酬 −0.005425;指數 0;超額 −0.005425(輸、虧)
    樣本 2(訊號日 t+1,進場 t+2 開盤 100):
      20 日:出場 t+21 收盤 90 → 報酬 −0.10 − 0.005425 = −0.105425;指數 102/100−1 = 0.02;超額 −0.125425(輸、虧)
      60 日:出場 t+61 收盤 100 → 報酬 −0.005425;超額 −0.005425(輸、虧)
    20 日:勝率 1/2 = 50%;虧損機率 1/2 = 50%;平均超額 (0.054575 − 0.125425)/2 = −0.03542 → −3.54%;中位數同(兩筆的平均)
          平均報酬 (0.094575 − 0.105425)/2 = −0.005425 → −0.54%
    60 日:勝率 0%;虧損機率 100%;平均超額 −0.54%"""
    T0 = 300
    COLS = ["A", "B", "C"]

    def setUp(self):
        t = self.T0
        self.close = pd.DataFrame(100.0, index=BT_DATES, columns=self.COLS)
        self.opn = pd.DataFrame(100.0, index=BT_DATES, columns=self.COLS)
        self.value = pd.DataFrame(1.0, index=BT_DATES, columns=self.COLS)
        self.chg = pd.DataFrame(0.0, index=BT_DATES, columns=self.COLS)
        self.close.iloc[t, 0:2], self.close.iloc[t + 1, 0:2] = 130.0, 140.0
        self.close.iloc[t + 20, 2], self.close.iloc[t + 21, 2] = 110.0, 90.0
        self.tx = pd.Series(100.0, index=BT_DATES)
        self.tx.iloc[t + 20], self.tx.iloc[t + 21] = 104.0, 102.0
        idx = pd.MultiIndex.from_tuples([(2026, 1)])
        self.yoy = pd.DataFrame([[10.0, 10.0, 50.0]], index=idx, columns=self.COLS)
        self.topics = {"alpha": self.COLS}

    def run_bt(self, n=None, **kw):
        sl = slice(None, n)
        c, o, v, g, tx = (x.iloc[sl] for x in (self.close, self.opn, self.value, self.chg, self.tx))
        L = laggard.launches(c, v, g)
        return laggard.backtest(c, o, tx, L, self.yoy, self.topics, **kw)

    def test_cost_constant(self):
        self.assertAlmostEqual(laggard.COST, 0.005425)

    def test_counts(self):
        r = self.run_bt()
        self.assertEqual(r["triggers"], 2)         # t、t+1 各觸發 alpha 一次
        self.assertEqual(r["signals"], 2)          # 每天入選 C 一檔
        self.assertEqual(list(r["samples"]["code"]), ["C", "C"])

    def test_stats_20(self):
        st = self.run_bt()["stats"]["20"]
        self.assertEqual((st["n"], st["stocks"]), (2, 1))
        self.assertEqual(st["win"], 50.0)
        self.assertEqual(st["loss"], 50.0)
        self.assertEqual(st["avg_rel"], -3.54)
        self.assertEqual(st["med_rel"], -3.54)
        self.assertEqual(st["avg"], -0.54)
        self.assertEqual(st["grade"], "樣本不足")   # n < 30

    def test_stats_60(self):
        st = self.run_bt()["stats"]["60"]
        self.assertEqual(st["n"], 2)
        self.assertEqual(st["win"], 0.0)
        self.assertEqual(st["loss"], 100.0)
        self.assertEqual(st["avg_rel"], -0.54)

    def test_missing_future_excluded(self):
        # 只留到 t+60:樣本 2 的 60 日出場在 t+61 沒資料 → 60 日只剩 1 筆(超額 −0.5425% → −0.54);20 日仍是 2 筆
        st = self.run_bt(n=self.T0 + 61)["stats"]
        self.assertEqual(st["20"]["n"], 2)
        self.assertEqual(st["60"]["n"], 1)
        self.assertEqual(st["60"]["avg_rel"], -0.54)

    def test_oos_split(self):
        # 樣本外 = 最後 oos_days 個交易日的訊號日(位置 ≥ len − oos_days)
        n = len(BT_DATES)
        all_oos = self.run_bt(oos_days=n - self.T0)["stats"]["20"]        # 位置 300、301 都在樣本外
        self.assertEqual((all_oos["oos_n"], all_oos["oos_avg_rel"]), (2, -3.54))
        one = self.run_bt(oos_days=n - self.T0 - 1)["stats"]["20"]        # 只有 301(樣本 2)在樣本外:超額 −12.54%
        self.assertEqual((one["oos_n"], one["oos_avg_rel"]), (1, -12.54))
        none = self.run_bt(oos_days=10)["stats"]["20"]
        self.assertEqual((none["oos_n"], none["oos_avg_rel"]), (0, None))

    def test_restricted_excluded(self):
        r = self.run_bt(restricted={"C"})
        self.assertEqual((r["triggers"], r["signals"], r["stats"]["20"]["n"]), (2, 0, 0))


if __name__ == "__main__":
    unittest.main()
