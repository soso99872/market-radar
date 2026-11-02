"""檢查 bench0050.py 的除息解析:用過去一段時間(2025-01 ～ 2026-10)跑同一套解析,印出 0050 的除息日和金額。"""
import json, sys, datetime as dt
sys.argv = ["x"]
import importlib.util
src = open("research/forward/bench0050.py", encoding="utf-8").read()
head = src.split("today = dt.date.today()")[0]          # 只取函式定義
g = {}; exec(head, g)
j = g["get"]("https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250101&endDate=20261031&response=json")
f = j.get("fields", []); print("fields:", f)
for r in j.get("data", []):
    if str(r[f.index("股票代號")]).strip() == "0050":
        print(g["roc"](r[0]), g["num"](r[f.index("權值+息值")]), r[:8])
