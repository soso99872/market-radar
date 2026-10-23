"""scripts/broker_stats.py 測試:手工建的小型固定股價,不讀 data/(LoadClosesTest 除外,僅確認格式)。

交易日 DATES[0..399] 用連續日曆日當序列;發布日 = DATES[10],基準價日 = DATES[9]。
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import broker_stats as bs  # noqa: E402

START = date(2025, 1, 1)
DATES = [(START + timedelta(days=i)).isoformat() for i in range(400)]
PUB = DATES[10]
TAIEX = {d: 100.0 for d in DATES}     # 預設大盤不動


def ev(broker="B", code="1111", target=110, d=PUB, dr=None, url="u"):
    return {"date": d, "code": code, "broker": broker, "target": target, "rating": None,
            "prev_target": None, "dir": dr, "urls": [url], "title": "t"}


def flat(v=100.0, **over):
    """全 v 的收盤,over = {"i<索引>": 價}。"""
    px = {d: v for d in DATES}
    for k, p in over.items():
        px[DATES[int(k[1:])]] = p
    return px


def sc(evs, px, tx=None):
    return bs.scores(evs, {"1111": px}, DATES, tx or TAIEX)


class MergeTest(unittest.TestCase):
    def test_7天內合併_8天不合併(self):
        a = ev(d="2025-03-01", url="a")
        b = ev(d="2025-03-08", url="b")       # 差 7 天 → 合併
        c = ev(d="2025-03-09", url="c")       # 與最早一筆差 8 天 → 不合併
        out = bs.merge([c, b, a])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["date"], "2025-03-01")
        self.assertEqual(out[0]["urls"], ["a", "b"])
        self.assertEqual(out[1]["date"], "2025-03-09")

    def test_不同券商_股票_目標價不合併(self):
        base = ev(d="2025-03-01")
        others = [ev(broker="X", d="2025-03-02"), ev(code="2222", d="2025-03-02"),
                  ev(target=120, d="2025-03-02")]
        self.assertEqual(len(bs.merge([base] + others)), 4)

    def test_日期取最早且不改動輸入(self):
        a, b = ev(d="2025-03-05", url="a"), ev(d="2025-03-02", url="b")
        out = bs.merge([a, b])
        self.assertEqual(out[0]["date"], "2025-03-02")
        self.assertEqual(out[0]["urls"], ["b", "a"])
        self.assertEqual(a["urls"], ["a"])

    def test_scores內部先合併(self):
        evs = [ev(d=DATES[10], url="a"), ev(d=DATES[12], url="b")]
        self.assertEqual(sc(evs, flat())["B"]["n"], 1)


class HitTest(unittest.TestCase):
    def many(self, n, **kw):
        """n 筆目標價各不同(不會合併)的紀錄,發布日各差 8 天。"""
        return [ev(target=110 + i, d=DATES[10 + i * 8], **kw) for i in range(n)]

    def test_基準價用前一交易日(self):
        # 基準價日 DATES[9] = 100;發布日當天(DATES[10])的 140 不影響基準價
        r = sc([ev(target=150)], flat(**{"i10": 140.0}))["B"]
        self.assertAlmostEqual(r["premium"], 0.5)

    def test_發布日非交易日取之前最後交易日(self):
        px = flat()
        px[DATES[9]] = 125.0
        # DATES[10] 是 2025-01-11;改成 DATES 沒有的日期(2025-01-10.5 不存在),用週期缺口模擬
        dates = DATES[:10] + DATES[11:]           # 拿掉 DATES[10],發布日 2025-01-11 非交易日
        r = bs.scores([ev(target=150, d=DATES[10])], {"1111": px}, dates, TAIEX)["B"]
        self.assertAlmostEqual(r["premium"], 0.2)

    def test_達標_收盤達目標價(self):
        px = flat(**{"i50": 110.0})               # 6 個月內某日收 110
        r = sc(self.many(10), px)["B"]["hit6"]
        self.assertEqual(r["n"], 10)
        self.assertAlmostEqual(r["rate"], 0.1)    # 目標價 110..119,只有 110 達標

    def test_收盤剛好等於目標價算達標_差一點不算(self):
        px = flat(**{"i50": 109.99})
        self.assertEqual(sc(self.many(10), px)["B"]["hit6"]["rate"], 0.0)

    def test_未滿期已達標也不算(self):
        evs = self.many(10) + [ev(target=105, d=DATES[390])]
        px = flat(**{"i395": 200.0})              # 已達標但還沒滿 126 日
        r = sc(evs, px)["B"]
        self.assertEqual(r["n"], 11)
        self.assertEqual(r["hit6"]["n"], 10)
        self.assertEqual(r["hit6"]["rate"], 0.0)

    def test_喊價幅度非正不算(self):
        evs = self.many(10) + [ev(target=100, d=DATES[100]), ev(target=90, d=DATES[110])]
        r = sc(evs, flat())["B"]
        self.assertEqual(r["n"], 12)
        self.assertEqual(r["hit6"]["n"], 10)      # 幅度 = 0、< 0 的不入分母
        want = (sum((110 + i) / 100 - 1 for i in range(10)) + 0.0 - 0.1) / 12
        self.assertAlmostEqual(r["premium"], want, places=3)   # 但喊價幅度平均含全部

    def test_6個月與12個月分開(self):
        px = {d: (110.0 if i >= 200 else 100.0) for i, d in enumerate(DATES)}   # 第 200 日起 110:超過 126、未超過 252
        evs = [ev(target=105 + i * 0.001, d=DATES[10]) for i in range(10)]   # 基準日 9:6 個月到 135、12 個月到 261
        r = sc(evs, px)["B"]
        self.assertEqual(r["hit6"]["rate"], 0.0)
        self.assertEqual(r["hit12"]["rate"], 1.0)

    def test_12個月未滿期不算(self):
        evs = [ev(target=110 + i, d=DATES[200 + i * 8]) for i in range(10)]   # base ~199,+252 > 399
        r = sc(evs, flat())["B"]
        self.assertEqual(r["hit12"]["n"], 0)
        self.assertIsNone(r["hit12"]["rate"])

    def test_樣本10筆有百分比_9筆不足(self):
        r10 = sc(self.many(10), flat())["B"]["hit6"]
        r9 = sc(self.many(9), flat())["B"]["hit6"]
        self.assertEqual((r10["n"], r10["rate"]), (10, 0.0))
        self.assertEqual(r9["n"], 9)
        self.assertIsNone(r9["rate"])

    def test_單日漲跌超過11pct排除_剛好11pct保留(self):
        px = {d: (112.0 if i >= 100 else 100.0) for i, d in enumerate(DATES)}   # 第 100 日 +12%
        r = sc(self.many(10), px)["B"]["hit6"]
        self.assertEqual(r["n"], 0)
        self.assertIsNone(r["rate"])
        px = {d: (111.0 if i >= 100 else 100.0) for i, d in enumerate(DATES)}    # 剛好 +11%
        self.assertEqual(sc(self.many(10), px)["B"]["hit6"]["n"], 10)

    def test_單日大跌超過11pct也排除(self):
        px = {d: (80.0 if i >= 100 else 100.0) for i, d in enumerate(DATES)}
        self.assertEqual(sc(self.many(10), px)["B"]["hit6"]["n"], 0)

    def test_未具名不計(self):
        evs = [ev(broker="未具名", target=110 + i, d=DATES[10 + i * 8]) for i in range(10)]
        self.assertEqual(sc(evs, flat()), {})


class DirectionTest(unittest.TestCase):
    def run_dir(self, dr, stock_end, taiex_end, n=10):
        """n 筆同日發布(目標價各異);基準日 DATES[9] 個股 100、大盤 100;
        第 9+63 日個股收 stock_end、大盤收 taiex_end(其餘日不變,避免單日跳動 > 11%)。"""
        evs = [ev(target=200 + i, d=DATES[10], dr=dr) for i in range(n)]
        px = flat(**{"i72": stock_end})
        tx = dict(TAIEX)
        tx[DATES[72]] = taiex_end
        return sc(evs, px, tx)["B"]

    def test_調升跑贏大盤(self):
        r = self.run_dir("up", 105.0, 102.0)      # 個股 +5% > 大盤 +2%
        self.assertEqual(r["up3"], {"n": 10, "rate": 1.0})
        self.assertEqual(r["down3"]["n"], 0)

    def test_調升沒跑贏大盤(self):
        self.assertEqual(self.run_dir("up", 101.0, 102.0)["up3"], {"n": 10, "rate": 0.0})

    def test_調降落後大盤(self):
        r = self.run_dir("down", 98.0, 102.0)
        self.assertEqual(r["down3"], {"n": 10, "rate": 1.0})
        self.assertEqual(r["up3"]["n"], 0)

    def test_調降沒落後大盤(self):
        self.assertEqual(self.run_dir("down", 105.0, 102.0)["down3"], {"n": 10, "rate": 0.0})

    def test_報酬相等不算跑贏(self):
        self.assertEqual(self.run_dir("up", 102.0, 102.0)["up3"]["rate"], 0.0)

    def test_keep與None不入方向(self):
        for dr in ("keep", None):
            r = self.run_dir(dr, 105.0, 102.0)
            self.assertEqual((r["up3"]["n"], r["down3"]["n"]), (0, 0))

    def test_方向9筆不足(self):
        r = self.run_dir("up", 105.0, 102.0, n=9)["up3"]
        self.assertEqual(r["n"], 9)
        self.assertIsNone(r["rate"])

    def test_方向未滿63日不算(self):
        evs = [ev(target=200 + i, d=DATES[340], dr="up") for i in range(10)]   # base=339,+63=402 > 399
        self.assertEqual(sc(evs, flat())["B"]["up3"]["n"], 0)

    def test_方向期間內單日超過11pct排除(self):
        evs = [ev(target=200 + i, d=DATES[10], dr="up") for i in range(10)]
        px = flat(**{"i30": 120.0})               # 一日 +20% 後回落
        self.assertEqual(sc(evs, px)["B"]["up3"]["n"], 0)


class PremiumTest(unittest.TestCase):
    def test_喊價幅度平均含所有紀錄(self):
        evs = [ev(target=120, d=DATES[10]), ev(target=80, d=DATES[395])]   # 後者未滿期、幅度為負
        self.assertAlmostEqual(sc(evs, flat())["B"]["premium"], 0.0)

    def test_沒有股價資料的紀錄略過(self):
        r = bs.scores([ev(code="9999")], {}, DATES, TAIEX)["B"]
        self.assertIsNone(r["premium"])
        self.assertEqual(r["n"], 1)


if __name__ == "__main__":
    unittest.main()
