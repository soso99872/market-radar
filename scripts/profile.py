"""個股基本資料:產業類別、主要業務、產品營收比重、概念股分類。給個股面板顯示,不參與選股與回測。

來源
  Yahoo 股市 公司資料頁   產業類別、主要經營業務、相關概念股(頁面只列前幾個)
  MoneyDJ 基本資料頁     營收比重(公司年報揭露的產品別比重,每年更新一次)、成立與上市日期、股本

對象是有個股面板的股票(data/stocks/*.json)。這些資料一年才變幾次,每檔 30 天重抓一次,
每次執行最多抓 MAX_PER_RUN 檔,避免拖長排程。

輸出 data/profile/latest.json
  {代號: {"ind", "biz", "mix": [[項目, 比重%]], "mix_year", "concepts": [...], "founded", "listed", "capital", "upd"}}
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

OUT = os.path.join(history.ROOT, "data", "profile", "latest.json")
IND_OUT = os.path.join(history.ROOT, "data", "profile", "industry.json")
STOCKS = os.path.join(history.ROOT, "data", "stocks")
STALE_DAYS = 30
MAX_PER_RUN = 120
PAUSE = 1.0
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"}


def fetch(url, encoding):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode(encoding, errors="replace")
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print("profile: %s %s" % (url, e), file=sys.stderr)
                return ""
            time.sleep(5 * (attempt + 1))


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).replace("\xa0", " ").strip()


def json_str(page, key):
    m = re.search(r'"%s":"((?:[^"\\]|\\.)*)"' % key, page)
    if not m:
        return None
    try:
        return json.loads('"%s"' % m.group(1)).strip() or None
    except ValueError:
        return None


def yahoo(code):
    out = {}
    for sfx in (".TW", ".TWO"):
        page = fetch("https://tw.stock.yahoo.com/quote/%s%s/profile" % (code, sfx), "utf-8")
        if '"business"' in page:
            break
    else:
        return out
    ind = json_str(page, "sectorName")
    out["ind"] = re.sub(r"^櫃", "", ind) if ind else None   # Yahoo 上櫃類股名前面加「櫃」
    biz = json_str(page, "business")
    if biz:
        out["biz"] = re.sub(r"\s*\n\s*", "", biz)   # 公司登記的業務說明常有硬斷行
    out["concepts"] = list(dict.fromkeys(
        html.unescape(n).strip() for n in re.findall(r'categoryLabel=%E6%A6%82%E5%BF%B5%E8%82%A1">([^<]{1,30})</a>', page)))
    return out


def moneydj(code):
    page = fetch("https://concords.moneydj.com/z/zc/zca/zca_%s.djhtm" % code, "big5")
    cells = [c for c in (text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", page, re.S)) if c]
    out = {}

    def after(label):
        try:
            v = cells[cells.index(label) + 1]
        except (ValueError, IndexError):
            return None
        return None if v in ("N/A", "") else v

    mix = after("營收比重")
    if mix:
        m = re.search(r"\((\d{4})年\)\s*$", mix)
        out["mix_year"] = int(m.group(1)) if m else None
        items = []
        for part in re.sub(r"\(\d{4}年\)\s*$", "", mix).split("、"):
            p = re.match(r"(.+?)(-?[\d.]+)%$", part.strip())
            if p:
                items.append([p.group(1).strip(), float(p.group(2))])
        if items:
            out["mix"] = items
    for key, label in (("founded", "成立時間"), ("listed", "初次上市(櫃)日期")):
        v = after(label)
        m = v and re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})$", v)
        if m:   # 民國年
            out[key] = "%d-%02d-%02d" % (int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    cap = after("股本(億, 台幣)")
    if cap:
        out["capital"] = history.num(cap)
    return out


def industry_map():
    """全部上市櫃公司的產業別(證交所產業代碼),起漲雷達算「同產業股價是否一起走強」用。每次執行都更新(只有兩個請求)。"""
    out = {}
    for url, kc, ki in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "公司代號", "產業別"),
                        ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "SecuritiesCompanyCode", "SecuritiesIndustryCode")):
        try:
            for r in history.get(url):
                c = str(r.get(kc, "")).strip()
                if history.STOCK.match(c) and str(r.get(ki, "")).strip():
                    out[c] = str(r.get(ki)).strip()
        except Exception as e:  # noqa: BLE001
            print("industry: %s %s" % (url, e), file=sys.stderr)
            return None
    return out


def main():
    ind = industry_map()
    if ind:
        os.makedirs(os.path.dirname(IND_OUT), exist_ok=True)
        with open(IND_OUT, "w", encoding="utf-8") as f:
            json.dump(ind, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    try:
        with open(OUT, encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        db = {}
    codes = sorted(fn[:-5] for fn in os.listdir(STOCKS) if fn.endswith(".json") and fn != "index.json")
    try:   # 查詢索引裡的其他股票也補(排在有面板的股票之後)
        with open(os.path.join(STOCKS, "index.json"), encoding="utf-8") as f:
            codes += sorted(set(json.load(f)["s"]) - set(codes))
    except (OSError, ValueError, KeyError):
        pass
    cutoff = (datetime.now(history.TZ) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    todo = [c for c in codes if db.get(c, {}).get("upd", "") < cutoff]
    order = {c: k for k, c in enumerate(codes)}
    todo.sort(key=lambda c: (db.get(c, {}).get("upd", ""), order[c]))   # 從沒抓過、最舊的優先;同樣沒抓過時有面板的先
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_PER_RUN
    today = datetime.now(history.TZ).strftime("%Y-%m-%d")
    done = 0
    for c in todo[:limit]:
        rec = {}
        rec.update(yahoo(c))
        time.sleep(PAUSE)
        rec.update(moneydj(c))
        time.sleep(PAUSE)
        if not rec.get("ind") and not rec.get("mix"):
            continue   # 兩邊都失敗就留著下次再試
        rec["upd"] = today
        db[c] = rec
        done += 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print("profile updated", done, "of", len(todo[:limit]), "| total", len(db), "| still stale", max(0, len(todo) - done))


if __name__ == "__main__":
    main()
