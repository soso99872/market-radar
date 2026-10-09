"""財報品質(地雷股檢查用):公開資訊觀測站的綜合損益表彙總與資產負債表彙總(一般產業),上市與上櫃全部公司。

損益表是年初到該季的累計數(千元),單季要相減(margin.quarterly 同樣的作法);資產負債表是該季底的時點數。
時間點與 margin.py 相同:一律假設到申報期限那天才知道,不偷看。

輸出
  data/quality/pl.json  {代號: {"2025Q2": [營業利益, 營業外收支, 稅前淨利, 本期淨利] 累計}}
  data/quality/bs.json  {代號: {"2025Q2": [流動資產, 資產總計, 流動負債, 負債總計, 股本, 保留盈餘, 權益總計]}}
用法:python scripts/quality.py         補缺期別 + 重抓最近兩季
      python scripts/quality.py 2018    從 2018 年起回補
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402
import margin  # noqa: E402

DIR = os.path.join(history.ROOT, "data", "quality")
PAUSE = 4
TABLES = {
    "pl": ("ajax_t163sb04", ["營業利益（損失）", "營業外收入及支出", "稅前淨利（淨損）", "本期淨利（淨損）"]),
    "bs": ("ajax_t163sb05", ["流動資產", "資產總計", "流動負債", "負債總計", "股本", "保留盈餘", "權益總計"]),
}


def cells(row, tag):
    return [re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", c)))
            for c in re.findall(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), row, re.S | re.I)]


def fetch(api, cols, market, period):
    y, q = int(period[:4]), int(period[-1])
    body = urllib.parse.urlencode({"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                                   "TYPEK": market, "year": y - 1911, "season": "%02d" % q}).encode()
    page = None
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://mopsov.twse.com.tw/mops/web/" + api, data=body, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                page = r.read().decode("utf-8", errors="replace")
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print("quality: %s %s %s %s" % (api, market, period, e), file=sys.stderr)
                return None
            time.sleep(15 * (attempt + 1))
    if "查詢無資料" in page:
        return {}
    if "hasBorder" not in page:
        return None
    out = {}
    for tb in re.findall(r"<table[^>]*hasBorder.*?</table>", page, re.S | re.I):
        rows = re.findall(r"<tr.*?</tr>", tb, re.S | re.I)
        hdr = cells(rows[0], "th")
        if not all(c in hdr for c in cols):   # 只收一般產業的表(金融、保險欄位不同)
            continue
        ix = [hdr.index(c) for c in cols]
        for r in rows[1:]:
            c = cells(r, "td")
            if len(c) <= max(ix) or not history.STOCK.match(c[0]):
                continue
            out[c[0]] = [history.num(c[i]) for i in ix]
    return out


def load(kind):
    try:
        with open(os.path.join(DIR, kind + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def quarterly_pl(cum):
    """損益累計數 → 單季 {期別: [營業利益, 營業外, 稅前, 淨利]};缺上一季累計的 Q2~Q4 略過。"""
    out = {}
    for p, v in cum.items():
        q = int(p[-1])
        if q == 1:
            out[p] = v
            continue
        prev = cum.get("%sQ%d" % (p[:4], q - 1))
        if prev and all(x is not None for x in v + prev):
            out[p] = [a - b for a, b in zip(v, prev)]
    return out


def prev_quarters(p, n):
    y, q = int(p[:4]), int(p[-1])
    out = []
    for _ in range(n):
        out.append("%dQ%d" % (y, q))
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    return out


DEBT_MAX, NAV_MIN, NONOP_SHARE = 70, 10, 50   # 負債比 %、每股淨值 元、業外佔稅前淨利 %


def flags(plq, bs, period):
    """某一期(最新已過申報期限的一季)的地雷條件。plq = quarterly_pl(這檔),bs = 這檔的資產負債表 {期別: [...]}。
    回傳 {條件: 數值},只放成立的條件;資料不足的條件不判斷。"""
    out = {}
    four = [plq.get(p) for p in prev_quarters(period, 4)]
    if all(four):
        op, nonop, pre, ni = (sum(x[k] for x in four) for k in range(4))
        if op < 0:
            out["本業虧損"] = op   # 近 4 季營業利益合計(千元)
        if pre > 0 and nonop > pre * NONOP_SHARE / 100:
            out["獲利靠業外"] = round(nonop / pre * 100)
    b = bs.get(period)
    if b and all(x is not None for x in b):
        cur_a, assets, cur_l, liab, cap, retained, equity = b
        if assets and liab / assets * 100 > DEBT_MAX:
            out["負債比偏高"] = round(liab / assets * 100)
        if cur_l and cur_a / cur_l < 1:
            out["流動比率 < 100%"] = round(cur_a / cur_l * 100)
        if cap and equity / cap * 10 < NAV_MIN:
            out["淨值跌破面額"] = round(equity / cap * 10, 2)
        if retained < 0:
            out["累積虧損"] = retained
    return out


def roc(s):
    """民國日期 1151008 / 115/10/08 → 2026-10-08"""
    d = re.sub(r"\D", "", s or "")
    return "%d-%s-%s" % (int(d[:3]) + 1911, d[3:5], d[5:7]) if len(d) == 7 else None


def alerts():
    """目前被處置、被列注意的股票(證交所、櫃買中心官方公告)。只有當下的清單,沒有歷史,所以不能回測、只當事實提醒。"""
    out = {"fetched_at": datetime.now(history.TZ).isoformat(timespec="minutes"), "punish": {}, "notice": {}}
    try:
        for r in history.get("https://openapi.twse.com.tw/v1/announcement/punish"):
            c = str(r.get("Code", "")).strip()
            if history.STOCK.match(c):
                out["punish"][c] = {"period": r.get("DispositionPeriod"), "why": r.get("ReasonsOfDisposition"), "how": r.get("DispositionMeasures")}
        for r in history.get("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"):
            c = str(r.get("SecuritiesCompanyCode", "")).strip()
            if history.STOCK.match(c):
                out["punish"][c] = {"period": r.get("DispositionPeriod"), "why": r.get("DispositionReasons"), "how": None}
        for r in history.get("https://openapi.twse.com.tw/v1/announcement/notice"):
            c = str(r.get("Code", "")).strip()
            if history.STOCK.match(c):
                out["notice"][c] = {"date": roc(r.get("Date")), "why": r.get("TradingInfoForAttention")}
        for r in history.get("https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information"):
            c = str(r.get("SecuritiesCompanyCode", "")).strip()
            if history.STOCK.match(c):
                out["notice"][c] = {"date": roc(r.get("Date")), "why": r.get("TradingInformation")}
    except Exception as e:  # noqa: BLE001
        print("quality alerts:", e, file=sys.stderr)
        return
    with open(os.path.join(DIR, "alerts.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("quality alerts: 處置 %d 注意 %d" % (len(out["punish"]), len(out["notice"])))


def main():
    today = datetime.now(history.TZ).date()
    os.makedirs(DIR, exist_ok=True)
    alerts()
    if "--alerts" in sys.argv:
        return
    for kind, (api, cols) in TABLES.items():
        db = load(kind)
        have = {p for v in db.values() for p in v}
        start = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else min([int(p[:4]) for p in have] or [today.year - 1])
        periods = margin.ended_periods(start, today)
        todo = [p for p in periods if p not in have] + [p for p in periods[-2:] if p in have]
        for p in todo:
            for mk in ("sii", "otc"):
                rows = fetch(api, cols, mk, p)
                time.sleep(PAUSE)
                if rows is None:
                    continue
                for c, v in rows.items():
                    db.setdefault(c, {})[p] = v
                print("quality", kind, p, mk, len(rows), file=sys.stderr, flush=True)
        with open(os.path.join(DIR, kind + ".json"), "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        print("quality", kind, "done", len(todo), "periods")


if __name__ == "__main__":
    main()
