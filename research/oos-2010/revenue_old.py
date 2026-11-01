"""回補 2010-01 ~ 2017-12 月營收,格式與 scripts/revenue.py 相同(data/revenue/YYYY-MM.json)。
和 revenue.fetch_month 的差別:外國企業(KY)頁在早年可能不存在(404),視為該頁沒有公司,不當成失敗。
"""
import os, sys, json, time, html, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import history, revenue as R

def fetch_month(y, m):
    out, ok, notes = {}, True, []
    for mkt in ("sii", "otc"):
        for kind in ("0", "1"):
            url = "https://mopsov.twse.com.tw/nas/t21/%s/t21sc03_%d_%d_%s.html" % (mkt, y - 1911, m, kind)
            t = None
            for attempt in range(3):
                try:
                    req = urllib.request.Request(url, headers=history.UA)
                    with urllib.request.urlopen(req, timeout=40) as r:
                        t = r.read().decode("big5", "replace")
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 404 and kind == "1":
                        notes.append("%s KY 404" % mkt); t = ""; break
                    time.sleep(10)
                except Exception:  # noqa: BLE001
                    time.sleep(10)
            if t is None:
                ok = False; notes.append("%s-%s fail" % (mkt, kind)); continue
            for code, cells in R.ROW.findall(t):
                v = [history.num(html.unescape(x)) for x in R.CELL.findall(cells)]
                if v and v[0] is not None:
                    out[code] = [int(v[0]), None if v[4] is None else round(v[4], 2), None if v[3] is None else round(v[3], 2)]
            time.sleep(2)
    return out, ok, notes

os.makedirs(R.DIR, exist_ok=True)
log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "log-revenue.txt"), "w", encoding="utf-8")
for y in range(2010, 2018):
    for m in range(1, 13):
        p = R.path_for(y, m)
        if os.path.exists(p): continue
        d, ok, notes = fetch_month(y, m)
        msg = "%d-%02d n=%d ok=%s %s" % (y, m, len(d), ok, ";".join(notes))
        print(msg, flush=True); log.write(msg + "\n"); log.flush()
        if ok and len(d) >= 500:
            json.dump(d, open(p, "w", encoding="utf-8"), separators=(",", ":"))
