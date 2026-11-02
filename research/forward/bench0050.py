"""0050 含息報酬(2026-11-02 起):證交所日收盤 + 除息資料,息在除息日用當天收盤再投入。輸出 json。"""
import json, sys, time, urllib.request, datetime as dt
import numpy as np
START = dt.date(2026, 11, 2)
H = {"User-Agent": "Mozilla/5.0"}
def get(url):
    for k in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30))
        except Exception as e: err = e; time.sleep(10 * (k + 1))
    raise err
roc = lambda s: dt.date(int(s[:3]) + 1911, int(s[4:6]), int(s[7:9]))      # 115/11/02 或 115年11月02日
num = lambda s: float(str(s).replace(",", ""))
today = dt.date.today(); px = {}; m = START.replace(day=1)
while m <= today:
    j = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={m:%Y%m}01&stockNo=0050&response=json")
    ci = j["fields"].index("收盤價")
    for r in j.get("data", []):
        d = roc(r[0])
        if d >= START: px[d] = num(r[ci])
    m = (m + dt.timedelta(days=32)).replace(day=1); time.sleep(3)
j = get(f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={START:%Y%m%d}&endDate={today:%Y%m%d}&response=json")
f = j.get("fields", []); div = {}
for r in j.get("data", []):
    if str(r[f.index("股票代號")]).strip() == "0050":
        div[roc(r[0])] = num(r[f.index("權值+息值")])
ds = sorted(px); units, eq = 1.0, []
for d in ds:
    if d in div: units *= 1 + div[d] / px[d]
    eq.append(units * px[d])
eq = np.array(eq) / eq[0]; r = eq[1:] / eq[:-1] - 1
o = {"交易日": len(ds), "資料到": str(ds[-1]), "除息": {str(k): v for k, v in div.items()},
     "累積%": round((eq[-1] - 1) * 100, 2), "最大回撤%": round(float((eq / np.maximum.accumulate(eq) - 1).min() * 100), 2)}
if len(r) >= 245:
    o["年化%"] = round((eq[-1] ** (245 / len(r)) - 1) * 100, 2)
    o["夏普"] = round(float(r.mean() / r.std() * np.sqrt(245)), 2)
json.dump(o, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(o)
