"""回補 2004-01 ~ 2009-12 月營收(格式同 data/revenue)。2009 年前的彙總表網址沒有 _0/_1 後綴,也沒有外國企業頁。log 只記家數。"""
import os, sys, json, time, html, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import history, revenue as R
os.makedirs(R.DIR, exist_ok=True)
log = open(os.path.join(HERE, "log-revenue.txt"), "a", encoding="utf-8")
for y in range(2004, 2010):
    for m in range(1, 13):
        p = R.path_for(y, m)
        if os.path.exists(p): continue
        out, ok, notes = {}, True, []
        for mkt in ("sii", "otc"):
            t = None
            for suf in ("", "_0"):
                url = "https://mopsov.twse.com.tw/nas/t21/%s/t21sc03_%d_%d%s.html" % (mkt, y - 1911, m, suf)
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(urllib.request.Request(url, headers=history.UA), timeout=40) as r:
                            t = r.read().decode("big5", "replace")
                        break
                    except Exception:  # noqa: BLE001
                        time.sleep(5)
                if t is not None: break
            if t is None:
                ok = False; notes.append(mkt + " fail"); continue
            for code, cells in R.ROW.findall(t):
                v = [history.num(html.unescape(x)) for x in R.CELL.findall(cells)]
                if v and v[0] is not None:
                    out[code] = [int(v[0]), None if v[4] is None else round(v[4], 2), None if v[3] is None else round(v[3], 2)]
            time.sleep(2)
        msg = "%d-%02d n=%d ok=%s %s" % (y, m, len(out), ok, ";".join(notes))
        print(msg, flush=True); log.write(msg + "\n"); log.flush()
        if ok and len(out) >= 500:
            json.dump(out, open(p, "w", encoding="utf-8"), separators=(",", ":"))
