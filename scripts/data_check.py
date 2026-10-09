"""資料正確性抽查(研究用,不在每日排程裡跑):拿我們的資料和獨立來源比對。

  1 股價       隨機 40 檔 × 5 天的收盤價,對 Yahoo Finance(yfinance,未還原)
  2 月營收年增 用我們存的營收金額自己重算年增率,對公開資訊觀測站公布的年增率
  3 毛利率     最新一季毛利率,對 MoneyDJ 基本資料頁的「營業毛利率」
  4 還原股價   隨機抽檢:還原後單日漲跌超過 ±10.5% 的筆數(應該只剩新上市無漲跌幅限制的日子)

用法:python scripts/data_check.py > 報告.txt
"""
import random
import re
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

import history
import margin
import radar
import signals as S

random.seed(7)
days = history.load_days()
F, HI, LO, taiex, names = S.frames(days)
raw, chg = F["close_raw"], F["chg"]
dates = list(raw.index)
last = dates[-1]
liquid = [c for c in raw.columns if not pd.isna(raw.at[last, c]) and (F["value"][c].iloc[-20:].mean() or 0) > 3e7]

# ---- 1 股價 ----
print("[1] 收盤價 vs Yahoo Finance(未還原)")
import warnings  # noqa: E402
warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402
sample = random.sample(liquid, 40)
check_days = random.sample(dates[-250:-1], 5)
bad, n = [], 0
for c in sample:
    for sfx in (".TW", ".TWO"):
        h = yf.Ticker(c + sfx).history(start=min(check_days), end=pd.Timestamp(max(check_days)) + pd.Timedelta(days=3), auto_adjust=False)
        if len(h):
            break
    if not len(h):
        print("  %s 查無 Yahoo 資料" % c)
        continue
    h.index = h.index.strftime("%Y-%m-%d")
    for d in check_days:
        if d in h.index and not pd.isna(raw.at[d, c]):
            n += 1
            y = float(h.at[d, "Close"])
            if abs(y / raw.at[d, c] - 1) > 0.006:
                bad.append((c, names.get(c), d, raw.at[d, c], round(y, 2)))
    time.sleep(0.3)
print("  比對 %d 筆,差異 > 0.6%% 的 %d 筆" % (n, len(bad)))
for b in bad[:15]:
    print("   ", b)

# ---- 2 月營收年增 ----
print("\n[2] 月營收年增率:我們存的營收金額重算 vs 官方公布")
rp = radar.revenue_panels(raw.columns)
rev, yoy = rp["rev"], rp["yoy"]
calc = (rev / rev.shift(12) - 1) * 100
both = calc.notna() & yoy.notna() & (rev.shift(12) > 0)
diff = (calc - yoy).abs()[both]
d = diff.stack()
print("  比對 %d 筆,差異 > 1 個百分點 %d 筆(%.2f%%)" % (len(d), int((d > 1).sum()), (d > 1).mean() * 100))
big = d[d > 1].sort_values(ascending=False).head(8)
for k, v in big.items():
    m, c = (k[0], k[1]), k[2]
    print("    %d-%02d %s %s 官方 %.1f%% 重算 %.1f%%" % (m[0], m[1], c, names.get(c, ""), yoy.at[m, c], calc.at[m, c]))
# 差異多半是去年同月營收事後更正(官方年增用更正後的去年數字);看差異是否集中在少數公司
by_c = (d > 1).groupby(level=2).sum().sort_values(ascending=False)
print("  差異集中度:前 20 家公司佔 %.0f%%;差異中位數 %.1f 個百分點" % (by_c.head(20).sum() / max(1, by_c.sum()) * 100, d[d > 1].median()))
months = rp["months"]
print("  月份連續性:%s ~ %s 共 %d 個月,缺月 %s" % (months[0], months[-1], len(months),
      [m for m in pd.period_range("%d-%02d" % months[0], "%d-%02d" % months[-1], freq="M")
       if (m.year, m.month) not in set(months)][:5]))

# ---- 3 毛利率 ----
print("\n[3] 最新一季毛利率 vs MoneyDJ")
cum = margin.load()
ms = random.sample([c for c in liquid if c in cum], 25)
bad3, n3 = [], 0
for c in ms:
    q = margin.quarterly(cum[c])
    if not q:
        continue
    p = max(q)
    r, g = q[p]
    if not r:
        continue
    ours = g / r * 100
    try:
        page = urllib.request.urlopen(urllib.request.Request("https://concords.moneydj.com/z/zc/zca/zca_%s.djhtm" % c,
                                                             headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("big5", "replace")
    except Exception as e:  # noqa: BLE001
        print("  %s 讀取失敗 %s" % (c, e))
        continue
    import profile as P   # 與公司概況同一套解析
    cells = [x for x in (P.text(y) for y in re.findall(r"<td[^>]*>(.*?)</td>", page, re.S)) if x]
    try:
        gv = cells[cells.index("營業毛利率") + 1]
    except (ValueError, IndexError):
        continue
    m = re.match(r"(-?[\d.]+)%", gv)
    qm = re.search(r"獲利能力\((\d+)\.(\d)Q\)", " ".join(cells))
    if not m or not qm:
        continue
    their_p = "%dQ%s" % (int(qm.group(1)) + 1911, qm.group(2))
    if their_p != p:
        print("  %s 期別不同:我們 %s、MoneyDJ %s" % (c, p, their_p))
        continue
    n3 += 1
    v = float(m.group(1))
    if abs(v - ours) > 0.5:
        bad3.append((c, names.get(c), p, round(ours, 2), v))
    time.sleep(0.5)
print("  比對 %d 檔,差異 > 0.5 個百分點 %d 檔" % (n3, len(bad3)))
for b in bad3:
    print("   ", b)

# ---- 4 還原股價 ----
print("\n[4] 還原股價:單日漲跌超過 ±10.5% 的筆數")
r1 = F["close"] / F["close"].shift(1) - 1
big = r1.abs() > 0.105
print("  %d 筆,分布在 %d 檔(多為新上市前 5 日、無漲跌幅限制)" % (int(big.values.sum()), int(big.any().sum())))
