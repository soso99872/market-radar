"""2010 年前資料來源探測。依 PROTOCOL.md:只輸出 HTTP 狀態與筆數,不輸出任何價格、報酬或指數點位。"""
import json, sys, time, os, urllib.request
sys.path.insert(0, "scripts")
import history as H
out = {}
def cnt_rev(url):
    try:
        req = urllib.request.Request(url, headers=H.UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            t = r.read().decode("big5", "replace")
        return {"ok": True, "tr": t.count("<tr"), "bytes": len(t)}
    except Exception as e:
        return {"ok": False, "err": str(e)[:60]}
for y, m in [(2004, 1), (2005, 1), (2006, 6), (2007, 1), (2008, 6), (2009, 1), (2009, 12)]:
    roc = y - 1911
    for host in ("mopsov.twse.com.tw", "mops.twse.com.tw"):
        for mkt in ("sii", "otc"):
            for suf in ("", "_0"):
                u = "https://%s/nas/t21/%s/t21sc03_%d_%d%s.html" % (host, mkt, roc, m, suf)
                out["rev %d-%02d %s %s %s" % (y, m, host.split(".")[0], mkt, suf or "-")] = cnt_rev(u)
                time.sleep(1.5)
    print(y, m, flush=True)
for d in ["2004-02-11", "2005-01-04", "2007-01-02", "2009-01-05"]:
    ymd, sl = d.replace("-", ""), d.replace("-", "%2F")
    r = {}
    try:
        mi = H.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % ymd)
        r["twse_stocks"] = sum(len(t.get("data") or []) for t in mi.get("tables", []) if "證券代號" in (t.get("fields") or []))
        r["twse_has_index_table"] = any((t.get("fields") or [""])[0] == "指數" for t in mi.get("tables", []))
    except Exception as e: r["twse"] = "ERR " + str(e)[:60]
    time.sleep(3.5)
    try:
        q = H.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=%s&type=EW&response=json" % sl)
        r["tpex_rows"] = sum(len(t.get("data") or []) for t in q.get("tables", []))
    except Exception as e: r["tpex"] = "ERR " + str(e)[:60]
    time.sleep(3.5)
    out["px " + d] = r; print(d, flush=True)
json.dump(out, open("research/oos-pre2010/probe.json", "w"), ensure_ascii=False, indent=1)
