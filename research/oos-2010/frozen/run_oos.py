"""用凍結的規則跑指定期間(預設 2010~2018,也就是 2026-10-31 定規則時沒人看過的資料)。

用法:python run_oos.py [起日] [迄日]      先跑 prep.py
規則(凍結,不准改):
  名單   起漲雷達星等(營收創 12 月新高且年增 ≥30% 或連 2 月 ≥20%;近 60 日漲 ≥ 動能門檻、同產業 60 日均漲 ≥15% 各加 1 星;
         營收減速或外資 20 日大賣扣 1 星),首頁前 10 檔排序(星等 → 本月新公告 → 好進出 → 近 3 月營收年增,同產業最多 3 檔)
  買     每月營收公告後第一個交易日收盤出名單;名單內每檔等「收盤創 20 日新高」,隔天開盤買,每檔 = 總淨值 1/10,最多 10 檔;
         開盤漲停或沒開盤不買;候選到下一次公告失效
  賣     每次公告日星等 < 4 就隔天開盤賣
  成本   來回 0.585%
  兩個版本:A 動能門檻 20%(網站現行)、B 動能門檻 10%(2021~2026 逐年前進每年選到的)
"""
import sys, os, json, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import buy as U
from bt import metrics, index_eq, dates

a = sys.argv[1] if len(sys.argv) > 1 else None
b = sys.argv[2] if len(sys.argv) > 2 else "2019-01-01"
if a is None:   # 預設:營收滿 14 個月、股價滿 250 天之後才開始
    m0 = U.months[0]; rev_ok = pd.Timestamp(m0[0] + 1, m0[1], 1) + pd.DateOffset(months=3)
    a = max(str(rev_ok.date()), dates[min(250, len(dates) - 1)])
def yearly(e):
    yr = e.resample("YE").last(); return {str(k.year): round(float(v), 1) for k, v in ((yr / yr.shift(1).fillna(1) - 1) * 100).items()}
out = {"期間": [a, b]}
for lab, mo in (("A 動能20%(現行)", 20), ("B 動能10%(逐年前進選的)", 10)):
    U.MOM = mo
    e, t, x = U.sim(timing="brk", exit_k=4, start=a, end=b)
    out[lab] = {"指標": {k: round(float(v), 2) for k, v in metrics(e, t, x).items()}, "逐年%": yearly(e)}
ix = index_eq(a, b)
out["加權指數(不含息)"] = {"指標": {k: round(float(v), 2) for k, v in metrics(ix).items()}, "逐年%": yearly(ix)}
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "oos_result.json"), "w"), ensure_ascii=False, indent=1)
