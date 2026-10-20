"""題材資料檔(data/sectors/topics.json)的格式測試。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import topics  # noqa: E402


class TopicsFileTest(unittest.TestCase):
    def test_validate_passes(self):
        self.assertEqual(topics.validate(topics.load()), [])

    def test_ccl_members(self):
        ccl = [t for t in topics.load() if t["id"] == "ccl"][0]
        for c in ("2383", "6274", "6213", "6672"):
            self.assertIn(c, ccl["codes"])

    def test_by_code(self):
        m = topics.by_code()
        self.assertIn("ccl", m["2383"])
        self.assertTrue(all(isinstance(v, list) and v for v in m.values()))

    def test_coverage_at_least_80_percent(self):
        s4, _ = topics.star4_codes()
        cover = topics.by_code()
        self.assertGreaterEqual(sum(1 for c in s4 if c in cover) / len(s4), topics.MIN_COVER)


class ValidateRulesTest(unittest.TestCase):
    def good(self):
        return [{"id": "a1", "name": "甲", "sector": "ccl", "desc": "x", "codes": ["2383", "6274", "6213"]}]

    def test_good_sample(self):
        self.assertEqual(topics.validate(self.good()), [])

    def test_rejects_bad_cases(self):
        def bad(**kw):
            t = self.good()
            t[0].update(kw)
            return topics.validate(t)
        self.assertTrue(bad(id="A_1"))
        self.assertTrue(bad(sector="nope"))
        self.assertTrue(bad(codes=["2383", "6274"]))
        self.assertTrue(bad(codes=["2383", "6274", "6274"]))
        self.assertTrue(bad(codes=["2383", "6274", "99"]))
        self.assertTrue(bad(codes=["2383", "6274", "0000"]))
        self.assertTrue(topics.validate(self.good() + self.good()))


if __name__ == "__main__":
    unittest.main()
