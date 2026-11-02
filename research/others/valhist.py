"""補抓每月一份的本益比、股價淨值比、殖利率（上市：證交所 BWIBBU_d；上櫃：櫃買中心本益比查詢）。
每個月從 11 號開始往後找第一個有資料的交易日（對齊月營收換股日）。存到 data/valhist/YYYY-MM-DD.json：{代號: [本益比, 淨值比, 殖利率]}。
已經有的月份會跳過。只記筆數到 log，不印數值。
用法：python valhist.py 2005 2026"""
import json, os, sys, time, datetime as dt, urllib.request
OUT = "data/valhist"; os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0"}
LOG = open("research/others/log-valhist.txt", "a", encoding="utf-8")
def get(url):
    for k in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30))
        except Exception as e: err = e; time.sleep(15 * (k + 1))
    raise err
num = lambda s: (lambda t: float(t) if t not in ("", "-", "--", "N/A") else None)(str(s).replace(",", "").strip())
def parse(fields, rows):
    fi = lambda *keys: next((i for i, f in enumerate(fields) if any(k in f for k in keys)), None)
    c, pe, pb, y = fi("代號"), fi("本益比"), fi("淨值比"), fi("殖利率")
    if None in (c, pe, pb, y): return {}
    out = {}
    for r in rows:
        try: out[str(r[c]).strip()] = [num(r[pe]), num(r[pb]), num(r[y])]
        except Exception: pass
    return out
def twse(d):
    j = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={d:%Y%m%d}&selectType=ALL&response=json")
    if j.get("stat") != "OK": return {}
    if "fields" in j: return parse(j["fields"], j.get("data", []))
    t = (j.get("tables") or [{}])[0]; return parse(t.get("fields", []), t.get("data", []))
def tpex(d):
    j = get(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={d:%Y/%m/%d}&response=json")
    for t in j.get("tables", []):
        p = parse(t.get("fields", []), t.get("data", []))
        if p: return p
    return {}
y0, y1 = int(sys.argv[1]), int(sys.argv[2])
today = dt.date.today()
for y in range(y0, y1 + 1):
    for m in range(1, 13):
        first = dt.date(y, m, 11)
        if first > today: break
        if any(f.startswith(f"{y}-{m:02d}-") for f in os.listdir(OUT)): continue
        got = None
        for k in range(0, 10):
            d = first + dt.timedelta(days=k)
            if d.weekday() >= 5 or d > today: continue
            try: a = twse(d)
            except Exception as e: LOG.write(f"{d} twse ERR {str(e)[:60]}\n"); continue
            time.sleep(3)
            if not a: continue
            try: b = tpex(d)
            except Exception as e: b = {}; LOG.write(f"{d} tpex ERR {str(e)[:60]}\n")
            time.sleep(3)
            got = (d, a | b, len(a), len(b)); break
        if got:
            d, v, na, nb = got
            json.dump(v, open(f"{OUT}/{d}.json", "w", encoding="utf-8"), separators=(",", ":"))
            LOG.write(f"{d} 上市 {na} 上櫃 {nb}\n")
        else: LOG.write(f"{y}-{m:02d} 沒抓到\n")
        LOG.flush()
