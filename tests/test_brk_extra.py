"""radar.load_brk(讀 data/brokers/events.json 放進 extra.brk)的單元測試:用暫存檔,不碰真的 data/brokers。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import radar  # noqa: E402


def ev(code, date, broker="大摩", target=100):
    return {"date": date, "code": code, "broker": broker, "target": target, "rating": None,
            "prev_target": None, "dir": "keep", "urls": ["https://example.com/" + date], "title": "t"}


class LoadBrkTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "events.json")

    def write(self, text):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write(text)

    def test_missing(self):
        self.assertEqual(radar.load_brk(os.path.join(self.d, "none.json")), {})

    def test_bad_json(self):
        self.write("{壞掉")
        self.assertEqual(radar.load_brk(self.p), {})
        self.write("")
        self.assertEqual(radar.load_brk(self.p), {})

    def test_wrong_shape(self):
        self.write('{"a": 1}')
        self.assertEqual(radar.load_brk(self.p), {})

    def test_sorted_and_per_code(self):
        self.write(json.dumps([ev("2454", "2026-08-01"), ev("2330", "2026-09-01"), ev("2454", "2026-10-01")]))
        r = radar.load_brk(self.p)
        self.assertEqual([x["date"] for x in r["2454"]], ["2026-10-01", "2026-08-01"])
        self.assertEqual(len(r["2330"]), 1)
        self.assertNotIn("2317", r)

    def test_max_30(self):
        self.write(json.dumps([ev("2454", "2026-01-%02d" % (i % 28 + 1), target=i) for i in range(45)]))
        r = radar.load_brk(self.p)["2454"]
        self.assertEqual(len(r), 30)
        dates = [x["date"] for x in r]
        self.assertEqual(dates, sorted(dates, reverse=True))


if __name__ == "__main__":
    unittest.main()
