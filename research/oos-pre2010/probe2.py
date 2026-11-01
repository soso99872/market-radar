"""第二次探測(依 PROTOCOL.md:只輸出狀態、筆數、欄位名稱,不輸出任何數值)。"""
import json, sys, time, html, urllib.request
sys.path.insert(0, "scripts")
import history as H, revenue as R
out = {}
for y, m in [(2004, 1), (2006, 6), (2008, 6), (2009, 11)]:
    for mkt in ("sii", "otc"):
        u = "https://mopsov.twse.com.tw/nas/t21/%s/t21sc03_%d_%d.html" % (mkt, y - 1911, m)
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=H.UA), timeout=40) as r:
                t = r.read().decode("big5", "replace")
            rows = R.ROW.findall(t)
            ok = sum(1 for _, c in rows if (lambda v: v and v[0] is not None)([H.num(html.unescape(x)) for x in R.CELL.findall(c)]))
            out["rev %d-%02d %s" % (y, m, mkt)] = {"rows_parsed": len(rows), "rows_with_revenue": ok}
        except Exception as e:
            out["rev %d-%02d %s" % (y, m, mkt)] = "ERR " + str(e)[:60]
        time.sleep(2)
for d in ["2005-01-04", "2006-01-04", "2007-01-02", "2007-07-02", "2008-01-02"]:
    sl = d.replace("-", "%2F"); roc = "%d/%s" % (int(d[:4]) - 1911, d[5:].replace("-", "/"))
    r = {}
    try:
        q = H.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=%s&type=EW&response=json" % sl)
        r["new_api_rows"] = sum(len(t.get("data") or []) for t in q.get("tables", []))
    except Exception as e: r["new_api"] = "ERR " + str(e)[:60]
    time.sleep(3)
    try:
        q = H.get("https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d=%s" % roc)
        r["legacy_rows"] = len(q.get("aaData") or q.get("data") or []); r["legacy_keys"] = list(q.keys())[:8]
    except Exception as e: r["legacy"] = "ERR " + str(e)[:60]
    time.sleep(3)
    out["tpex " + d] = r
for d in ["20040201", "20050101", "20080101"]:
    try:
        q = H.get("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=%s&response=json" % d)
        out["FMTQIK " + d] = {"stat": q.get("stat"), "rows": len(q.get("data") or []), "fields": q.get("fields")}
    except Exception as e: out["FMTQIK " + d] = "ERR " + str(e)[:60]
    time.sleep(3.5)
try:
    mi = H.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20050104&type=ALLBUT0999&response=json")
    out["MI_INDEX 2005 table fields"] = [(t.get("title"), (t.get("fields") or [])[:9]) for t in mi.get("tables", [])]
except Exception as e: out["MI_INDEX 2005"] = "ERR " + str(e)[:60]
json.dump(out, open("research/oos-pre2010/probe2.json", "w"), ensure_ascii=False, indent=1)
print("done")
