"""高峰風險判定(radar.peak_risk)的單元測試:固定資料,不連網。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import radar  # noqa: E402

M3 = [(2026, 7), (2026, 8), (2026, 9)]
YOY = [(m, 40.0) for m in M3]
BH = [1.6] * 30           # P/B 歷史中位數 1.6


def run(method="pe", fair=130.0, price=100.0, pb=2.0, bh=BH, yoy=YOY, months3=M3):
    return radar.peak_risk(method, fair, price, pb, bh, yoy, months3)


class PeakRiskTest(unittest.TestCase):
    def test_all_three_trigger(self):     # 年增 40、fair 130、P/B 合理價 100/2.5×1.6 = 64 ≤ 80
        self.assertTrue(run(pb=2.5, fair=130))

    def test_missing_yoy_cond(self):
        self.assertFalse(run(yoy=[(m, 40.0) for m in M3[:2]] + [(M3[2], 29.9)]))

    def test_missing_fair_cond(self):
        self.assertFalse(run(fair=119.9))

    def test_missing_pb_cond(self):
        self.assertFalse(run(pb=2.0, bh=[2.0] * 30))   # P/B 合理價 = 100,不低估於 80

    def test_boundary_all(self):
        self.assertTrue(run(fair=120.0, pb=2.0, yoy=[(m, 30.0) for m in M3]))   # 30%、1.2、0.8 剛好

    def test_method_pb(self):
        self.assertFalse(run(method="pb", pb=2.5))

    def test_no_current_pb(self):
        self.assertFalse(run(pb=None))
        self.assertFalse(run(pb=0))

    def test_pb_history_short(self):
        self.assertFalse(run(pb=2.5, bh=[1.6] * 23))
        self.assertFalse(run(pb=2.5, bh=[None] * 30))

    def test_revenue_not_latest_month(self):
        old = [(2026, 5), (2026, 6), (2026, 7)]
        self.assertFalse(run(pb=2.5, yoy=[(m, 40.0) for m in old]))

    def test_revenue_less_than_3_months(self):
        self.assertFalse(run(pb=2.5, yoy=YOY[1:]))
        self.assertFalse(run(pb=2.5, yoy=[(M3[0], None), (M3[1], 40.0), (M3[2], 40.0)]))


if __name__ == "__main__":
    unittest.main()
