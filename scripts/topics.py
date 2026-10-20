"""題材清單(data/sectors/topics.json)的讀取與格式檢查。

題材是板塊(themes.json)底下更細的分群,例如「銅箔基板」板塊下的「CCL 銅箔基板」。
一檔股票可屬於多個題材。供「落後補漲」等功能使用。

用法:
  from topics import load, by_code
  python scripts/topics.py check   驗證格式,並印出起漲雷達 4★ 以上個股的題材覆蓋率
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPICS = os.path.join(ROOT, "data", "sectors", "topics.json")
THEMES = os.path.join(ROOT, "data", "sectors", "themes.json")
RADAR = os.path.join(ROOT, "data", "radar", "latest.json")
MIN_CODES = 3
MIN_COVER = 0.8
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load():
    """回傳題材清單(list of dict:id、name、sector、desc、codes)。"""
    return _read(TOPICS)


def by_code(topics=None):
    """代號 → 題材 id 清單。"""
    out = {}
    for t in topics if topics is not None else load():
        for c in t["codes"]:
            out.setdefault(c, []).append(t["id"])
    return out


def star4_codes():
    """起漲雷達 4★ 以上個股:與 radar.html 的 starOf() 相同,取 latest.json 的 rev、theme 兩份清單裡的 stars。"""
    r = _read(RADAR)
    stars = {}
    for x in (r.get("rev") or []) + (r.get("theme") or []):
        stars[x["code"]] = x.get("stars") or 1
    return {c: s for c, s in stars.items() if s >= 4}, {x["code"]: x.get("name", "") for x in (r.get("rev") or []) + (r.get("theme") or [])}


def validate(topics):
    """回傳錯誤訊息清單(空 = 通過)。"""
    errs = []
    if not isinstance(topics, list) or not topics:
        return ["topics.json 必須是非空陣列"]
    sectors = {t["id"] for t in _read(THEMES)}
    dates = history.all_dates()
    known = set(history.load_day(dates[-1])["s"]) if dates else set()
    if not dates:
        errs.append("找不到任何 history 檔,無法檢查代號是否存在於最新 history")
    seen_ids = set()
    for i, t in enumerate(topics):
        tid = t.get("id")
        tag = "第 %d 筆(%s)" % (i + 1, tid)
        for k in ("id", "name", "sector", "desc", "codes"):
            if not t.get(k):
                errs.append("%s 缺欄位 %s" % (tag, k))
        if not isinstance(tid, str) or not ID_RE.match(tid):
            errs.append("%s id 必須是英數小寫(可用 - 分隔)" % tag)
        if tid in seen_ids:
            errs.append("%s id 重複" % tag)
        seen_ids.add(tid)
        if t.get("sector") not in sectors:
            errs.append("%s sector「%s」不在 themes.json" % (tag, t.get("sector")))
        codes = t.get("codes") or []
        if len(codes) < MIN_CODES:
            errs.append("%s 只有 %d 檔,至少 %d 檔" % (tag, len(codes), MIN_CODES))
        if len(set(codes)) != len(codes):
            errs.append("%s 題材內代號重複" % tag)
        for c in codes:
            if not (isinstance(c, str) and re.match(r"^\d{4}$", c)):
                errs.append("%s 代號「%s」不是 4 碼數字" % (tag, c))
            elif dates and c not in known:
                errs.append("%s 代號 %s 不在最新 history 檔(%s)" % (tag, c, dates[-1]))
    return errs


def check():
    topics = load()
    errs = validate(topics)
    cover = by_code(topics)
    s4, names = star4_codes()
    miss = sorted(c for c in s4 if c not in cover)
    rate = (len(s4) - len(miss)) / len(s4) if s4 else 0.0
    n_codes = sum(len(t["codes"]) for t in topics)
    print("題材 %d 個,代號合計 %d 檔(不重複 %d 檔)" % (len(topics), n_codes, len(cover)))
    print("4★ 以上 %d 檔,有題材 %d 檔,覆蓋率 %.1f%%(門檻 %d%%)" % (len(s4), len(s4) - len(miss), rate * 100, MIN_COVER * 100))
    print("未覆蓋(%d 檔):%s" % (len(miss), "、".join("%s %s(%d★)" % (c, names.get(c, ""), s4[c]) for c in miss)))
    if rate < MIN_COVER:
        errs.append("4★ 以上覆蓋率 %.1f%% 低於 %d%%" % (rate * 100, MIN_COVER * 100))
    for e in errs:
        print("錯誤:" + e)
    print("通過" if not errs else "失敗(%d 項)" % len(errs))
    return 0 if not errs else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["check"]:
        sys.exit(check())
    print(__doc__)
    sys.exit(2)
