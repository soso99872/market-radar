"""第三方稽核:用 anti-gambling-trader(mars-tw/anti-gambling-trader-tw)檢驗「照營收動能名單每月一籃」的成績。

輸入是 radar.py 產生的兩份交易紀錄(都已扣掉同日一般股的報酬,且每籃不重疊,符合它的前提):
  data/track/basket_backtest.csv  回測(規則是看過歷史才定的,僅供參考)
  data/track/basket_live.csv      實盤追蹤(名單每天存檔後不再修改,這份才是真正的檢驗)
輸出 data/track/audit.json。

用法:python scripts/audit.py <anti-gambling-trader 目錄> [版本 sha]
需要 Python 3.10+(稽核工具的要求);本腳本只用標準函式庫。
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACK = os.path.join(ROOT, "data", "track")
MIN_TRADES = 10   # 少於這個數就不送檢,避免小樣本給出誤導的裁決


def rows(path):
    try:
        with open(path, encoding="utf-8") as f:
            return list(csv.reader(f))[1:]
    except FileNotFoundError:
        return []


def run(agt, path):
    n = len(rows(path))
    if n < MIN_TRADES:
        return {"n": n, "status": "樣本不足", "need": MIN_TRADES}
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.json")
        p = subprocess.run([sys.executable, "-m", "core.cli", "analyze", path, "--market", "tw_stock", "--json", out],
                           cwd=agt, capture_output=True, text=True, encoding="utf-8",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if not os.path.exists(out):
            return {"n": n, "status": "執行失敗", "error": (p.stderr or p.stdout)[-500:]}
        with open(out, encoding="utf-8") as f:
            d = json.load(f)
    v, sig, oos = d["verdict"], d["verdict"].get("significance", {}), d.get("out_of_sample") or {}
    m = v.get("metrics", {})
    return {
        "n": n, "status": "ok", "level": v["level"], "headline": v["headline"],
        "win_rate": m.get("win_rate"), "expectancy": m.get("expectancy"),
        "p_t": sig.get("p_value_t"), "p_boot": sig.get("p_value_bootstrap"),
        "ci": [sig.get("ci_low"), sig.get("ci_high")],
        "oos_persisted": oos.get("edge_persisted"), "oos_summary": oos.get("summary") or oos.get("verdict"),
    }


def main():
    agt = sys.argv[1]
    sha = sys.argv[2] if len(sys.argv) > 2 else ""
    doc = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes"),
        "tool": "anti-gambling-trader-tw", "tool_sha": sha,
        "unit": "每月一籃,投入 100 萬,損益 = 名單等權報酬 − 同日一般股平均報酬(已扣交易成本)",
        "backtest": run(agt, os.path.join(TRACK, "basket_backtest.csv")),
        "live": run(agt, os.path.join(TRACK, "basket_live.csv")),
        # 星等評級 4★ 以上(2026-10-09 加入):回測紀錄由 scripts/explosion_study.py 產生,規則是看過 2019–2026 才定的
        "backtest_star": run(agt, os.path.join(TRACK, "basket_backtest_star.csv")),
        "live_star": run(agt, os.path.join(TRACK, "basket_live_star.csv")),
    }
    with open(os.path.join(TRACK, "audit.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(json.dumps(doc, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
