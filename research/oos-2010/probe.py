"""查各資料來源最早有資料的時間(只讀,不存 data/)。"""
import json, sys, time, os
sys.path.insert(0, "scripts")
import history as H
out = {}
def tw(d):
    ymd = d.replace("-", "")
    r = {}
    try:
        t = H.get("https://www.twse.com.tw/rwd/zh/fund/T86?date=%s&selectType=ALLBUT0999&response=json" % ymd)
        r["T86"] = [t.get("stat"), len(t.get("data") or [])]
    except Exception as e: r["T86"] = ["ERR", str(e)[:80]]
    time.sleep(3.5)
    try:
        m = H.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % ymd)
        n = sum(len(t.get("data") or []) for t in m.get("tables", []) if "證券代號" in (t.get("fields") or []))
        r["MI_INDEX"] = [m.get("stat"), n]
    except Exception as e: r["MI_INDEX"] = ["ERR", str(e)[:80]]
    time.sleep(3.5)
    sl = d.replace("-", "/").replace("/", "%2F")
    try:
        q = H.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=%s&type=EW&response=json" % sl)
        r["TPEx_quote"] = sum(len(t.get("data") or []) for t in q.get("tables", []))
    except Exception as e: r["TPEx_quote"] = "ERR " + str(e)[:80]
    time.sleep(1)
    try:
        q = H.get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=%s&response=json" % sl)
        r["TPEx_inst"] = len(((q.get("tables") or [{}])[0]).get("data") or [])
    except Exception as e: r["TPEx_inst"] = "ERR " + str(e)[:80]
    time.sleep(1)
    return r
for d in ["2008-01-07", "2010-01-05", "2011-01-04", "2012-01-04", "2012-05-02", "2013-01-03", "2014-01-03", "2016-01-05", "2018-01-03"]:
    out[d] = tw(d); print(d, out[d], flush=True)
import urllib.request
for y, m in [(2008, 1), (2009, 1), (2010, 1), (2011, 1), (2012, 1), (2013, 1), (2015, 6)]:
    res = {}
    for mkt in ("sii", "otc"):
        url = "https://mopsov.twse.com.tw/nas/t21/%s/t21sc03_%d_%d_0.html" % (mkt, y - 1911, m)
        try:
            req = urllib.request.Request(url, headers=H.UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                t = r.read().decode("big5", "replace")
            res[mkt] = [len(t), t.count("<tr")]
        except Exception as e:
            res[mkt] = "ERR " + str(e)[:80]
        time.sleep(2)
    out["rev %d-%02d" % (y, m)] = res; print(y, m, res, flush=True)
json.dump(out, open("research/oos-2010/probe.json", "w"), ensure_ascii=False, indent=1)
