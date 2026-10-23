"""逐家券商目標價紀錄計算(純函式,不連網)。

輸入的事件格式:
  {date:"YYYY-MM-DD", code, broker, target, rating, prev_target, dir:"up"|"down"|"keep"|None, urls:[...], title}
股價資料:
  closes = {代號: {日期: 收盤}}   dates = 交易日序列(舊 → 新)   taiex = {日期: 加權指數收盤}

定義(PRD sprint 003 A 第 8 點):
  基準價 = 發布日前一交易日收盤;喊價幅度 = 目標價 / 基準價 - 1
  6 / 12 個月 = 126 / 252 個交易日;達標 = 期間內任一日收盤 >= 目標價
  只算「喊價幅度 > 0 且已滿期」的紀錄;期間內個股單日漲跌超過 ±11%(除權、減資等)的紀錄不算
  方向:dir=up 滿 63 個交易日,個股報酬 > 同期大盤報酬的比例;down 則為 < 的比例
  任一項樣本 < 10 筆 → rate=None(畫面顯示「紀錄不足」)
  「未具名」不計。
"""
import bisect
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

MIN_N = 10                  # 樣本門檻
MERGE_DAYS = 7              # 同一份報告合併的天數
H6, H12, H3 = 126, 252, 63  # 交易日數
JUMP = 0.11                 # 單日漲跌超過此值視為無效(除權、減資等)
ANON = "未具名"


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def merge(events):
    """同券商、同股票、同目標價、發布日相差 <= 7 天合併成一筆(日期取最早,urls 合併)。
    天數與該組最早一筆比較(不連鎖延長)。回傳依日期排序的新 list,不改動輸入。"""
    groups = {}
    for e in sorted(events, key=lambda x: x["date"]):
        groups.setdefault((e["broker"], e["code"], e["target"]), []).append(e)
    out = []
    for lst in groups.values():
        cur = None
        for e in lst:
            if cur is not None and (_d(e["date"]) - _d(cur["date"])).days <= MERGE_DAYS:
                for u in e.get("urls") or []:
                    if u not in cur["urls"]:
                        cur["urls"].append(u)
                # 最早那篇缺的欄位,用同一份報告的其他篇補
                for k in ("rating", "prev_target", "dir"):
                    if cur.get(k) is None and e.get(k) is not None:
                        cur[k] = e[k]
                continue
            cur = dict(e)
            cur["urls"] = list(e.get("urls") or [])
            out.append(cur)
    out.sort(key=lambda x: (x["date"], x["broker"], x["code"]))
    return out


def _rate(hit, n):
    return {"n": n, "rate": round(hit / n, 4) if n >= MIN_N else None}


def _jumpy(px, dates, a, b):
    """dates[a..b] 之間是否有單日漲跌 > 11%,或缺收盤價(視為無效)。"""
    for i in range(a + 1, b + 1):
        p0, p1 = px.get(dates[i - 1]), px.get(dates[i])
        if not p0 or not p1:
            return True
        if round(abs(p1 / p0 - 1), 6) > JUMP:  # round 避免剛好 11% 的浮點誤差
            return True
    return False


def scores(events, closes, dates, taiex):
    """每家券商的紀錄 {券商: {n, hit6, hit12, premium, up3, down3}}。"""
    pos = {}
    for e in merge([x for x in events if x.get("broker") and x["broker"] != ANON]):
        pos.setdefault(e["broker"], []).append(e)
    last = len(dates) - 1
    out = {}
    for broker, evs in pos.items():
        prem, h6, h12, up, dn = [], [0, 0], [0, 0], [0, 0], [0, 0]
        for e in evs:
            px = closes.get(e["code"]) or {}
            i = bisect.bisect_left(dates, e["date"])  # 發布日(或之後第一個交易日)
            b = i - 1                                 # 基準價日 = 發布日前一交易日
            base = px.get(dates[b]) if b >= 0 else None
            if not base:
                continue
            p = e["target"] / base - 1
            prem.append(p)
            # 達標:6 / 12 個月,必須喊價幅度 > 0、已滿期、期間內無異常跳動
            for h, acc in ((H6, h6), (H12, h12)):
                if p <= 0 or b + h > last or _jumpy(px, dates, b, b + h):
                    continue
                acc[1] += 1
                if any((px.get(dates[j]) or 0) >= e["target"] for j in range(b + 1, b + h + 1)):
                    acc[0] += 1
            # 方向:3 個月相對大盤
            if e.get("dir") in ("up", "down") and b + H3 <= last and not _jumpy(px, dates, b, b + H3):
                t0, t1 = taiex.get(dates[b]), taiex.get(dates[b + H3])
                p1 = px.get(dates[b + H3])
                if t0 and t1 and p1:
                    r, m = p1 / base - 1, t1 / t0 - 1
                    acc = up if e["dir"] == "up" else dn
                    acc[1] += 1
                    if (r > m) if e["dir"] == "up" else (r < m):
                        acc[0] += 1
        out[broker] = {
            "n": len(evs),
            "hit6": _rate(*h6),
            "hit12": _rate(*h12),
            "premium": round(sum(prem) / len(prem), 4) if prem else None,
            "up3": _rate(*up),
            "down3": _rate(*dn),
        }
    return out


def load_closes(codes, since):
    """讀 data/history 的收盤價。回傳 (closes, dates, taiex)。
    since = 'YYYY-MM-DD',只讀該日(含)以後。dates 為所有交易日(舊 → 新)。"""
    codes = set(codes)
    closes = {c: {} for c in codes}
    dates, taiex = [], {}
    for d in history.all_dates():
        if d < since:
            continue
        day = history.load_day(d)
        dates.append(d)
        if day.get("taiex"):
            taiex[d] = day["taiex"][0]
        s = day.get("s") or {}
        for c in codes:
            row = s.get(c)
            if row and len(row) > 4 and row[4]:
                closes[c][d] = row[4]
    return closes, dates, taiex
