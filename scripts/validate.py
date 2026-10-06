"""檢查每日報告 JSON 是否符合網站需要的格式。用法: python scripts/validate.py data/2026-10-07.json"""
import json
import sys

REQUIRED = ["date", "generated_at", "headline", "sentiment", "markets",
            "key_points", "calendar", "sources"]
IMPACT = {"利多", "利空", "中性", "視數據而定"}
IMPORTANCE = {"高", "中", "低"}


def fail(msg):
    print("INVALID:", msg)
    sys.exit(1)


def main(path):
    with open(path, encoding="utf-8") as f:
        r = json.load(f)
    for k in REQUIRED:
        if k not in r:
            fail("missing key " + k)
    s = r["sentiment"]
    if s.get("label") not in {"偏多", "中性", "偏空"} or not isinstance(s.get("score"), int) \
            or not -2 <= s["score"] <= 2:
        fail("sentiment needs label 偏多/中性/偏空 and integer score -2..2")
    for g in r["markets"]:
        for it in g.get("items", []):
            for k in ("symbol", "name", "last", "change_pct"):
                if k not in it:
                    fail("market item missing %s: %r" % (k, it))
    for p in r["key_points"]:
        if p.get("impact") not in IMPACT:
            fail("key_point impact must be one of %s: %r" % (IMPACT, p.get("title")))
    for c in r["calendar"]:
        if c.get("importance") not in IMPORTANCE:
            fail("calendar importance must be 高/中/低: %r" % c.get("event"))
    if not r["sources"]:
        fail("sources must not be empty")
    with open("data/index.json", encoding="utf-8") as f:
        idx = json.load(f)
    if r["date"] not in idx.get("dates", []):
        fail("data/index.json does not list " + r["date"])
    print("OK", path)


if __name__ == "__main__":
    main(sys.argv[1])
