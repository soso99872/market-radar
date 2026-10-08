"""季度毛利率:公開資訊觀測站「綜合損益表彙總」(一般產業),上市與上櫃全部公司一次抓。

彙總表是年初到該季的累計數(千元),單季 = 本期累計 − 上期累計。金融、保險等沒有毛利的產業不在一般產業表裡,不收。

時間點:季報最晚的申報期限是 Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31。回測一律假設到期限那天才知道,
不用實際公布日(多數公司會提早),寧可保守也不偷看未來。

輸出 data/margin/cum.json  {代號: {"2025Q2": [營收累計, 毛利累計], ...}}   (千元)
用法:python scripts/margin.py           補齊缺的期別 + 重抓最近兩季(陸續有公司公布)
      python scripts/margin.py 2019     從 2019 年起回補
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

OUT = os.path.join(history.ROOT, "data", "margin", "cum.json")
URL = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"
PAUSE = 4
DEADLINE = {1: (5, 15), 2: (8, 14), 3: (11, 14), 4: (3, 31)}   # Q4 是隔年


def available(period):
    """該季財報最晚可取得的日期(ISO)。"""
    y, q = int(period[:4]), int(period[-1])
    m, d = DEADLINE[q]
    return date(y + (q == 4), m, d).isoformat()


def ended_periods(start_year, today):
    out = []
    for y in range(start_year, today.year + 1):
        for q in range(1, 5):
            end = date(y, q * 3, 30 if q in (2, 3) else 31)
            if end < today:
                out.append("%dQ%d" % (y, q))
    return out


def cells(row, tag):
    return [re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", c)))
            for c in re.findall(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), row, re.S | re.I)]


def fetch(market, period):
    y, q = int(period[:4]), int(period[-1])
    body = urllib.parse.urlencode({"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                                   "TYPEK": market, "year": y - 1911, "season": "%02d" % q}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, data=body, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                page = r.read().decode("utf-8", errors="replace")
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print("margin: %s %s %s" % (market, period, e), file=sys.stderr)
                return None
            time.sleep(15 * (attempt + 1))
    if "查詢無資料" in page or "hasBorder" not in page:
        return {} if "查詢無資料" in page else None
    out = {}
    for tb in re.findall(r"<table[^>]*hasBorder.*?</table>", page, re.S | re.I):
        rows = re.findall(r"<tr.*?</tr>", tb, re.S | re.I)
        hdr = cells(rows[0], "th")
        if "營業收入" not in hdr:
            continue
        gp_col = "營業毛利（毛損）淨額" if "營業毛利（毛損）淨額" in hdr else "營業毛利（毛損）"
        if gp_col not in hdr:
            continue
        i_rev, i_gp = hdr.index("營業收入"), hdr.index(gp_col)
        for r in rows[1:]:
            c = cells(r, "td")
            if len(c) <= max(i_rev, i_gp) or not history.STOCK.match(c[0]):
                continue
            rev, gp = history.num(c[i_rev]), history.num(c[i_gp])
            if rev is not None and gp is not None:
                out[c[0]] = [rev, gp]
    return out


def quarterly(cum):
    """把一檔的累計數轉成單季 {期別: (營收, 毛利)};缺上一季累計的 Q2~Q4 無法還原,略過。"""
    out = {}
    for p, (rev, gp) in cum.items():
        q = int(p[-1])
        if q == 1:
            out[p] = (rev, gp)
            continue
        prev = cum.get("%sQ%d" % (p[:4], q - 1))
        if prev:
            out[p] = (rev - prev[0], gp - prev[1])
    return out


def load():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    db = load()
    have = {p for v in db.values() for p in v}
    today = datetime.now(history.TZ).date()
    start = int(sys.argv[1]) if len(sys.argv) > 1 else min([int(p[:4]) for p in have] or [today.year - 1])
    periods = ended_periods(start, today)
    todo = [p for p in periods if p not in have] + [p for p in periods[-2:] if p in have]
    n = 0
    for p in todo:
        for mk in ("sii", "otc"):
            rows = fetch(mk, p)
            time.sleep(PAUSE)
            if rows is None:
                continue
            for c, v in rows.items():
                db.setdefault(c, {})[p] = v
            n += len(rows)
            print("margin", p, mk, len(rows))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print("margin done", len(todo), "periods,", n, "rows")


if __name__ == "__main__":
    main()
