"""模型合理價:用公開資料、固定公式算出來的估值,不含任何人為判斷。

公式(本益比河流圖的作法,加上營收動能調整):
  近四季 EPS   = 股價 ÷ 本益比(證交所/櫃買中心公布的本益比,以最近四季財報計算)
  營收動能倍數 = 近 3 個月營收 × 4 ÷ 近 12 個月營收,限制在 0.7 ~ 1.8 倍(假設淨利率不變)
  預估 EPS     = 近四季 EPS × 營收動能倍數
  合理價       = 預估 EPS × 這檔股票自己過去 5 年本益比的中位數(每月快照,至少 24 個月)
  合理區間     = 預估 EPS × 歷史本益比第 25 ~ 75 百分位
  評價狀態     = 股價低於區間下緣「低估」、高於上緣「高估」、其餘「合理」
虧損或本益比 > 100 的公司改用股價淨值比:合理價 = 每股淨值 × 歷史淨值比中位數(不做營收調整)。
"""
import numpy as np
import pandas as pd

GROWTH_CLIP = (0.7, 1.8)
MIN_HIST = 24
MAX_HIST = 60
PE_MAX = 100


def band(hist, lo_cut=0, hi_cut=PE_MAX):
    v = np.array([x for x in hist if x is not None and not pd.isna(x) and lo_cut < x <= hi_cut], dtype=float)
    if len(v) < MIN_HIST:
        return None
    v = v[-MAX_HIST:]
    return np.percentile(v, 25), np.percentile(v, 50), np.percentile(v, 75), len(v)


def estimate(price, pe, pb, rev_ttm, rev_3m, pe_hist, pb_hist):
    """回傳 dict 或 None。pe_hist / pb_hist:過去每月快照(舊 → 新,不含當月)。"""
    if not price or price <= 0:
        return None
    if pe and 0 < pe <= PE_MAX:
        b = band(pe_hist)
        if b:
            eps = price / pe
            g = 1.0
            if rev_ttm and rev_3m and rev_ttm > 0:
                g = float(np.clip(rev_3m * 4 / rev_ttm, *GROWTH_CLIP))
            feps = eps * g
            lo, mid, hi, n = b
            return {"method": "pe", "eps": eps, "growth": g, "feps": feps, "band": [lo, mid, hi], "n": n,
                    "fair": feps * mid, "low": feps * lo, "high": feps * hi}
    if pb and pb > 0:
        b = band(pb_hist, 0, 50)
        if b:
            bvps = price / pb
            lo, mid, hi, n = b
            return {"method": "pb", "bvps": bvps, "band": [lo, mid, hi], "n": n,
                    "fair": bvps * mid, "low": bvps * lo, "high": bvps * hi}
    return None


def status(price, est):
    if est["low"] > 0 and price < est["low"]:
        return "低估"
    if price > est["high"]:
        return "高估"
    return "合理"
