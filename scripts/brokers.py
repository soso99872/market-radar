"""逐家券商目標價:經濟日報新聞標題／內文解析(純函式,不連網)。

來源是經濟日報搜尋「目標價」的新聞(前半解析,後半抓取、合併、輸出)。規則式解析,不用 LLM:
  parse(title, body, names) -> [{code, broker, target, rating, dir, prev_target}, ...]
    title  新聞標題(可含 <u> 等標籤)
    body   內文純文字,可為 None;標題抽不到券商或金額時才看內文
    names  全市場 {代號: 名稱}(用 load_names() 取得),或 build_index(names) 的結果
無法明確解析(券商、股票、金額對不起來)就不產生事件。

dir 依 PRD A 第 8 點優先順序,本檔做 ① 與 ③:
  ① 新聞寫明前次目標價(例「從 6,055 元調升至 6,800 元」)→ 兩數比較,並填 prev_target
  ③ 關鍵字:調升／上修／調高／上調 → up,調降／下修／調低／下調 → down,維持／重申 → keep
  都沒有 → None。② 與我們前一筆比較,存檔前用 apply_dir 補(覆蓋 ③,不覆蓋 ①)。

用法:python scripts/brokers.py [--backfill] [--check]
  預設抓搜尋前 3 頁;--backfill 抓到最後一頁;--check 只驗證 data/brokers/events.json(AC-B2)。
"""
import argparse
import glob
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "history")
OUT_DIR = os.path.join(ROOT, "data", "brokers")
EVENTS = os.path.join(OUT_DIR, "events.json")
SCORES = os.path.join(OUT_DIR, "scores.json")
SEEN = os.path.join(OUT_DIR, "seen.json")   # 已處理過的網址(含沒產生事件的),重跑跳過

UNNAMED = "未具名"

# 外資券商:正規名稱 → 寫法(新聞用的簡稱、別名)。對照不到的具名券商照原名,不在此表就不認得
FOREIGN_BROKERS = {
    "摩根士丹利": ["摩根士丹利", "大摩"],
    "摩根大通": ["摩根大通", "小摩"],
    "美銀證券": ["美銀證券", "美銀美林", "美國銀行", "美銀", "美林"],
    "高盛": ["高盛"],
    "瑞銀": ["瑞銀"],
    "花旗": ["花旗環球", "花旗證券", "花旗"],
    "麥格理": ["麥格理"],
    "里昂證券": ["里昂證券", "法商里昂", "里昂"],
    "野村": ["野村"],
    "滙豐": ["滙豐", "匯豐"],
    "德意志": ["德意志", "德銀"],
    "巴克萊": ["巴克萊"],
    "大和": ["大和資本", "大和證券", "大和"],
    "瑞穗": ["瑞穗"],
    "星展": ["星展"],
    "法巴": ["法國巴黎", "法巴"],
    "杰富瑞": ["杰富瑞"],
    "CLSA": ["CLSA"],
}
# 本土券商:單獨的名字可能是股票(統一、國泰…),所以要求後面接「證券／投顧／證」,
# 或是不會跟股票撞名的(凱基、元大…,後面不接「金」「控」「銀」)
DOMESTIC_BROKERS = {
    "凱基": ["凱基"], "元大": ["元大"], "富邦": ["富邦"], "群益": ["群益"], "永豐": ["永豐"],
    "統一": ["統一"], "國泰": ["國泰"], "中信": ["中信"], "兆豐": ["兆豐"], "第一金": ["第一金"],
    "華南永昌": ["華南永昌"], "日盛": ["日盛"], "玉山": ["玉山"], "康和": ["康和"],
    "宏遠": ["宏遠"], "台新": ["台新"], "國票": ["國票"], "新光": ["新光"], "合庫": ["合庫"],
}
# 只寫這些詞、沒寫券商名的,記「未具名」
UNNAMED_RE = re.compile(r"外資|法人|投顧|券商|大行|外商|亞系|美系|歐系|日系|分析師")

# 股票簡稱(資料裡的全名去掉後綴之外的常見說法)
STOCK_ALIASES = {
    "台積": "2330", "日月光": "3711", "台達": "2308", "華邦": "2344", "鴻準": "4062",
    "聯發": "2454",
}

_NAME_SUFFIX = re.compile(r"(-KY|-創|-DR|\*)+$")

_UP_RE = re.compile(r"調升|上修|調高|上調|大升|同步升|升至|升到|升目標|升[^，。；\s]{0,6}?目標價|提高目標價")
_DOWN_RE = re.compile(r"調降|下修|調低|下調|降至|降到|降目標|降[^，。；\s]{0,6}?目標價")
# ③ 的維持／重申只在後面接目標價時才算(「重申買進」只是評等)
_KEEP_RE = re.compile(r"(?:維持|重申)(?:[^，,。；;、\s]|(?<=\d),(?=\d)){0,10}?(?:目標價|目標股價)|目標價(?:維持|不變)")
# 標題寫了調升／調降卻沒給前次目標價 → 內文找「從 X 元…至 Y 元」補 prev_target
_MOVE_RE = re.compile(r"調(?!整|查)|上修|下修|升至|降至|升到|降到|大升|提高")

_RATINGS = "強力買進|買進|買入|增持|優於大盤|跑贏大盤|超越大盤|加碼|中立|中性|持有|減碼|減持|賣出|劣於大盤|落後大盤|表現遜於大盤"
_RATING_RE = re.compile(r"[「『](" + _RATINGS + r")[」』]|(" + _RATINGS + r")(?=評等)|(?:評等|建議|給予|維持|予以)(?:至|為|於|調升至|調降至)?[「『]?(" + _RATINGS + ")")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_BAD_UNIT = r"(?!\d)(?![.,]\d)(?![\d,.]*[美港日歐%％倍億萬月日年檔家張季點成度xX])(?![–—~～-]\d)"   # 後面接單位或「480–500」這種範圍都不是目標價
# 「從 X 元…至 Y 元」「由 X 元直衝 Y 元」「從 500 元升到 725 元」
_FROM_TO = re.compile(r"[從由]\s*(" + _NUM + r")\s*元?\s*([^\d，。；、]{0,14}?)\s*(" + _NUM + r")\s*元")
# 金額觸發:強觸發可省略「元」;弱觸發一定要有「元」
_STRONG = r"(?:目標價維持|目標價為|目標價|目標股價|調升至|上調至|調高至|上修至|調降至|下調至|下修至|提高至|升至|升到|降至|降到|喊到|喊|上看)"
_WEAK = r"(?:看到|看|為|至|到|達)"
_AMT_STRONG = re.compile(_STRONG + r"\s*(" + _NUM + r")" + _BAD_UNIT + r"(元)?((?:、" + _NUM + r"元?)*)")
_AMT_WEAK = re.compile(_WEAK + r"\s*(" + _NUM + r")\s*元((?:、" + _NUM + r"元?)*)")
# 「維持4,750元目標價」這種金額在前、目標價在後的寫法
_AMT_POST = re.compile(r"(" + _NUM + r")\s*元\s*(?:的)?目標(?:股)?價")
_TP_RE = re.compile(r"目標價|目標股價")
# 非目標價的金額:前 15 字(最近一個「元」之後)有獲利類字眼;彭博／平均／共識的目標價;年份
_EPS_RE = re.compile(r"EPS|每股純益|每股盈餘|獲利|營收", re.I)
_CONSENSUS_RE = re.compile(r"彭博|平均|共識")
_YEAR_RE = re.compile(r"(?:19|20)\d\d")
_FX_RE = re.compile(r"人民幣|美元|美金|日圓|港幣|ADR")


class _Index:
    """名稱比對用的索引:股票名稱與券商寫法合成一個正規表示式,同位置取最長。"""

    def __init__(self, names):
        stock = {}   # 名稱／簡稱 → 代號
        for code, name in names.items():
            if not name or len(name) < 2:
                continue
            stock[name] = code
        for code, name in names.items():            # 去後綴的簡稱(臻鼎-KY → 臻鼎),不蓋掉全名
            short = _NAME_SUFFIX.sub("", name or "")
            if len(short) >= 2 and short not in stock:
                stock[short] = code
        for short, code in STOCK_ALIASES.items():
            if code in names and short not in stock:
                stock[short] = code
        self.stock = stock
        self.broker = {}   # 寫法 → 正規名稱
        forms = []         # (排序用長度, 正規表示式片段)
        for canon, aliases in FOREIGN_BROKERS.items():
            for a in aliases:
                self.broker[a] = canon
                forms.append((len(a), re.escape(a)))
        for canon, aliases in DOMESTIC_BROKERS.items():
            for a in aliases:
                self.broker[a] = canon
                forms.append((len(a) + 2, re.escape(a) + r"(?:證券|投顧|證)"))
                if a not in stock:     # 不會撞到股票名的,單獨寫也算(後面不接金／控／銀／台灣)
                    forms.append((len(a), re.escape(a) + r"(?![金控銀台])"))
        for s in stock:
            forms.append((len(s), re.escape(s)))
        forms.sort(key=lambda x: -x[0])
        self.regex = re.compile("|".join(p for _, p in forms))

    def find(self, text):
        """回傳依出現順序、不重疊的 [(起, 迄, 'stock'|'broker', 值)]。"""
        out = []
        pos = 0
        for m in self.regex.finditer(text):
            if m.start() < pos:
                continue
            s = m.group(0)
            kind, val = None, None
            base = _broker_base(s, self.broker)
            if s in self.stock:
                kind, val = "stock", self.stock[s]
            elif base is not None:
                kind, val = "broker", base
            if kind:
                out.append((m.start(), m.end(), kind, val))
                pos = m.end()
        return out


def _broker_base(s, table):
    """比對到的字串 → 正規券商名;不是券商回傳 None。本土券商去掉「證券／投顧／證」後綴再查。"""
    if s in table:
        return table[s]
    for suf in ("證券", "投顧", "證"):
        if s.endswith(suf) and s[:-len(suf)] in table:
            return table[s[:-len(suf)]]
    return None


def build_index(names):
    return _Index(names)


def load_names(root=ROOT):
    """從 data/history 最新一天的 s 取全市場 {代號: 名稱}。"""
    files = sorted(glob.glob(os.path.join(root, "data", "history", "*", "*.json.gz")))
    if not files:
        return {}
    with gzip.open(files[-1], "rt", encoding="utf-8") as f:
        s = json.load(f).get("s", {})
    return {code: v[0] for code, v in s.items()}


# ---------- 文字處理 ----------

_FULL = str.maketrans("０１２３４５６７８９，．", "0123456789,.")


def _clean(text):
    """去標籤、全形數字轉半形、連續空白壓成一個。換行保留給內文斷句。"""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = text.translate(_FULL)
    text = re.sub(r"[ \t　\xa0]+", " ", text)
    return text


def _num(s):
    v = float(s.replace(",", ""))
    return int(v) if v == int(v) else v


def _first(regex, *texts):
    for t in texts:
        m = regex.search(t)
        if m:
            return m
    return None


def _direction(prev, target, *texts):
    """① 有前次目標價就比較;③ 否則看關鍵字(同時有調升與調降視為不明)。"""
    if prev is not None:
        return "up" if target > prev else "down" if target < prev else "keep"
    for t in texts:
        up, down = bool(_UP_RE.search(t)), bool(_DOWN_RE.search(t))
        if up != down:
            return "up" if up else "down"
        if up and down:
            return None
        if _KEEP_RE.search(t):
            return "keep"
    return None


def _rating(*texts):
    for t in texts:
        m = _RATING_RE.search(t)
        if m:
            return next(g for g in m.groups() if g)
    return None


def _foreign(clause, pos):
    """目標價前面緊接外幣／ADR(例「人民幣目標價至6.4」「台積電ADR目標價」)→ 不是台幣目標價。"""
    tp = max(clause.rfind("目標價", 0, pos + 1), clause.rfind("目標股價", 0, pos + 1))
    head = clause[max(0, tp - 4):tp] if tp >= 0 else ""
    return bool(_FX_RE.search(head))


def _not_target(clause, start, num_at, num, yuan):
    """這個金額不是目標價(EPS 等獲利金額、彭博／平均／共識目標價、年份)就回傳 True。
    start = 金額（含觸發詞）在子句的起點;num_at = 數字本身的起點;yuan = 數字後面有沒有「元」。
    EPS 類字眼只看數字前 15 字,且只看最近一個「元」或「目標價」之後(前面的字眼屬於別的金額)。"""
    head = clause[max(0, num_at - 15):num_at]
    for cut in ("元", "目標價", "目標股價"):
        head = head[head.rfind(cut) + 1:] if cut in head else head
    if _EPS_RE.search(head):
        return True
    if _CONSENSUS_RE.search(clause[max(0, start - 8):start + 6]):
        return True
    if not yuan and _YEAR_RE.fullmatch(num):
        return True
    return False


def _amounts(clause, carry_tp):
    """抽出子句裡的目標價 [(位置, 目標價, 前次目標價)]。子句沒有「目標價」且前面也沒有時不抽。"""
    if not (_TP_RE.search(clause) or carry_tp):
        return []
    found, used = [], []
    for m in _FROM_TO.finditer(clause):
        if _not_target(clause, m.start(), m.start(3), m.group(3), True):
            continue
        found.append((m.start(), _num(m.group(3)), _num(m.group(1))))
        used.append((m.start(), m.end()))

    def free(a, b):
        return not any(a < ue and us < b for us, ue in used)

    for m in _AMT_STRONG.finditer(clause):
        if not free(m.start(), m.end()):
            continue
        if _foreign(clause, m.start()):
            continue
        if _not_target(clause, m.start(), m.start(1), m.group(1), bool(m.group(2))):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
        for extra in re.findall(_NUM, m.group(3) or ""):
            if not _YEAR_RE.fullmatch(extra):
                found.append((m.start(), _num(extra), None))
    for m in _AMT_WEAK.finditer(clause):
        if not free(m.start(), m.end()):
            continue
        if _foreign(clause, m.start()):
            continue
        if _not_target(clause, m.start(), m.start(1), m.group(1), True):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
        for extra in re.findall(_NUM, m.group(2) or ""):
            if not _YEAR_RE.fullmatch(extra):
                found.append((m.start(), _num(extra), None))
    for m in _AMT_POST.finditer(clause):
        if not free(m.start(), m.end()) or _foreign(clause, m.start()):
            continue
        if _not_target(clause, m.start(), m.start(1), m.group(1), True):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
    found.sort(key=lambda x: x[0])
    return [(p, t, pv) for p, t, pv in found if t > 0]


def _analyze(text, idx, title="", fallback_stocks=()):
    """解析一段文字(標題或內文),回傳事件 list。"""
    events = []
    carry_broker = None
    carry_tp = False
    for sentence in re.split(r"[。！？\n]+", text) if "\n" in text or "。" in text else [text]:
        sentence = sentence.strip()
        if not sentence:
            continue
        for clause in sentence.split("；"):
            ents = idx.find(clause)
            stocks = list(dict.fromkeys(v for _, _, k, v in ents if k == "stock"))
            # 「台積電（2330）」括號代號也算
            for m in re.finditer(r"[（(](\d{4,5})[）)]", clause):
                if m.group(1) in idx.stock.values() and m.group(1) not in stocks:
                    stocks.append(m.group(1))
            brokers = list(dict.fromkeys(v for _, _, k, v in ents if k == "broker"))
            amts = _amounts(clause, carry_tp)
            has_tp = bool(_TP_RE.search(clause))
            if len(brokers) == 1:
                carry_broker = brokers[0]
            if has_tp:
                carry_tp = True
            if not amts:
                continue
            if not stocks and len(fallback_stocks) == 1:
                stocks = list(fallback_stocks)
            if not stocks:
                continue
            if brokers:
                bl = brokers
            elif UNNAMED_RE.search(clause):
                bl = [UNNAMED]
            elif carry_broker:
                bl = [carry_broker]
            else:
                continue
            pairs = _pair(stocks, bl, amts)
            ctx = (clause, sentence, title)
            for code, broker, (_, target, prev) in pairs:
                events.append({
                    "code": code, "broker": broker, "target": target,
                    "rating": _rating(clause, sentence),
                    "dir": _direction(prev, target, *ctx),
                    "prev_target": prev,
                })
    uniq, seen = [], set()
    for e in events:
        k = (e["code"], e["broker"], e["target"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def _pair(stocks, brokers, amts):
    """金額要能明確對應:一個金額 ↔ 一檔、一家;多個金額時,檔數(或家數)要剛好等於金額數。"""
    n = len(amts)
    if n == 1:
        if len(stocks) == 1 and len(brokers) == 1:
            return [(stocks[0], brokers[0], amts[0])]
        return []
    if len(stocks) == n and len(brokers) == 1:
        return [(stocks[i], brokers[0], amts[i]) for i in range(n)]
    if len(brokers) == n and len(stocks) == 1 and UNNAMED not in brokers:
        return [(stocks[0], brokers[i], amts[i]) for i in range(n)]
    return []


def needs_body(title, events):
    """標題解析的結果還要不要抓內文:沒事件、有未具名、或標題寫調升／調降卻沒有前次目標價。"""
    if not events or any(e["broker"] == UNNAMED for e in events):
        return True
    return bool(_MOVE_RE.search(_clean(title))) and any(e["prev_target"] is None for e in events)


def parse(title, body, names):
    """標題優先;標題抽不到券商或金額、或缺前次目標價時再用內文補。
    回傳 [{code, broker, target, rating, dir, prev_target}]。"""
    idx = names if isinstance(names, _Index) else build_index(names)
    title = _clean(title).replace("\n", " ")
    t_events = _analyze(title, idx)
    if not body or not needs_body(title, t_events):
        return t_events
    t_stocks = list(dict.fromkeys(v for _, _, k, v in idx.find(title) if k == "stock"))
    b_events = _analyze(_clean(body), idx, title=title, fallback_stocks=t_stocks)
    if t_stocks:
        b_events = [e for e in b_events if e["code"] in t_stocks]
    result = []
    for e in t_events:
        for b in b_events:      # 內文有同檔同金額的事件:補具名券商、前次目標價
            if b["code"] == e["code"] and b["target"] == e["target"]:
                prev = e["prev_target"] if e["prev_target"] is not None else b["prev_target"]
                broker = b["broker"] if e["broker"] == UNNAMED and b["broker"] != UNNAMED else e["broker"]
                e = dict(e, broker=broker, rating=e["rating"] or b["rating"], prev_target=prev,
                         dir=_direction(prev, e["target"]) if prev is not None else e["dir"] or b["dir"])
                break
        result.append(e)
    if not t_events or any(e["broker"] == UNNAMED for e in t_events):
        have = {e["code"] for e in result}
        result += [b for b in b_events if b["code"] not in have]
    return result


# ---------- 抓取、合併、輸出 ----------

SEARCH = "https://money.udn.com/search/result/1001/" + urllib.parse.quote("目標價") + "/{page}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT, RETRIES, GAP = 20, 2, 1.0
DEFAULT_PAGES, MAX_PAGES = 3, 80
DIR_DAYS = 365

_ITEM = re.compile(
    r'<a href="(https://money\.udn\.com/money/story/\d+/\d+)[^"]*"[^>]*data-slotname="list_搜尋結果頁"[^>]*title="([^"]*)"'
    r'.*?<time>(\d{4}-\d{2}-\d{2})[^<]*</time>', re.S)
_last_req = [0.0]


def fetch(url):
    """GET 網頁文字。間隔 >= 1 秒、逾時 20 秒、失敗重試 2 次,仍失敗就丟例外。"""
    err = None
    for i in range(RETRIES + 1):
        wait = GAP - (time.time() - _last_req[0])
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (i + 1))
    raise err


def parse_search(page_html):
    """搜尋結果頁 → [{url, title, date}](只取結果清單,不含側欄推薦)。"""
    return [{"url": u, "title": html.unescape(t), "date": d} for u, t, d in _ITEM.findall(page_html)]


def parse_article(page_html):
    """文章頁 → 正文純文字(只取 article_body 段落,不含廣告與側欄;不存檔)。"""
    m = re.search(r'id\s*=\s*"article_body"(.*?)id="story_end"', page_html, re.S)
    if not m:
        return ""
    paras = re.findall(r"<p>(.*?)</p>", m.group(1), re.S)
    out = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in paras]
    return "\n".join(p for p in out if p)


def _days(a, b):
    return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days


def apply_dir(events):
    """dir 規則 ②:沒有前次目標價(① 沒結果)的事件,跟同券商對同檔 365 天內的前一筆比較。
    前一筆 = 日期較早、且不是同一份報告(同目標價 7 天內)的最近一筆;相同 → keep。
    找不到前一筆就保留原本的(③ 關鍵字)。回傳新 list,不改動輸入。"""
    evs = sorted((dict(e) for e in events), key=lambda e: (e["date"], e["code"], e["broker"]))
    last = {}   # (券商, 代號) → 已處理的事件們(舊 → 新)
    for e in evs:
        if e["broker"] == UNNAMED:
            continue
        prevs = last.setdefault((e["broker"], e["code"]), [])
        if e.get("prev_target") is None:
            cands = [p for p in prevs
                     if 0 < _days(p["date"], e["date"]) <= DIR_DAYS
                     and not (p["target"] == e["target"] and _days(p["date"], e["date"]) <= 7)]
            if cands:
                p = cands[-1]
                e["dir"] = "up" if e["target"] > p["target"] else "down" if e["target"] < p["target"] else "keep"
                e["prev_target"] = p["target"]
        prevs.append(e)
    return evs


RATIO_MIN, RATIO_MAX = 0.3, 5   # 目標價 ÷ 發布日前一交易日收盤 的合理範圍
DROPPED = []                    # 本次執行被合理性過濾丟掉的 (網址, 代號, 券商, 目標價, 比例)


def make_base_fn():
    """回傳 base_fn(代號, 日期) → 發布日前一交易日收盤(查不到回 None);讀 data/history,逐日快取。"""
    import bisect
    import history
    dates = history.all_dates()
    cache = {}

    def base_fn(code, date):
        i = bisect.bisect_left(dates, date) - 1
        if i < 0:
            return None
        d = dates[i]
        if d not in cache:
            cache[d] = history.load_day(d).get("s") or {}
        row = cache[d].get(code)
        return row[4] if row and len(row) > 4 and row[4] else None
    return base_fn


def ratio(base_fn, code, date, target):
    """目標價 ÷ 前一交易日收盤;沒有 base_fn 或查不到收盤回 None(保留)。"""
    base = base_fn(code, date) if base_fn else None
    return target / base if base else None


def collect(fetch_fn, names, seen, pages, existing, log=print, base_fn=None):
    """抓搜尋頁 → 解析 → (事件 list, seen set, 單篇失敗數, 搜尋頁是否失敗)。fetch_fn(url) → 文字。"""
    idx = build_index(names)
    seen = set(seen)
    events = list(existing)
    fail = 0
    for page in range(1, pages + 1):
        try:
            items = parse_search(fetch_fn(SEARCH.format(page=page)))
        except urllib.error.HTTPError as e:
            if e.code == 404 and page > 1:   # 超過最後一頁,經濟日報回 404
                break
            log("搜尋頁 %d 失敗:%s" % (page, e))
            return events, seen, fail, True
        except Exception as e:  # noqa: BLE001
            log("搜尋頁 %d 失敗:%s" % (page, e))
            return events, seen, fail, True
        if not items:
            break
        for it in items:
            if it["url"] in seen:
                continue
            try:
                found = parse(it["title"], None, idx)
                if needs_body(it["title"], found):
                    body = parse_article(fetch_fn(it["url"]))
                    found = parse(it["title"], body, idx)
            except Exception as e:  # noqa: BLE001
                fail += 1
                log("單篇失敗,略過:%s %s" % (it["url"], e))
                continue
            seen.add(it["url"])
            for f in found:
                r = ratio(base_fn, f["code"], it["date"], f["target"])
                if r is not None and not RATIO_MIN <= r <= RATIO_MAX:
                    DROPPED.append((it["url"], f["code"], f["broker"], f["target"], round(r, 3)))
                    log("合理性過濾丟棄:%s %s %s %s(目標價/收盤 %.2f)" % (it["url"], f["code"], f["broker"], f["target"], r))
                    continue
                events.append({"date": it["date"], "code": f["code"], "broker": f["broker"], "target": f["target"],
                               "rating": f["rating"], "prev_target": f["prev_target"], "dir": f["dir"],
                               "urls": [it["url"]], "title": re.sub(r"<[^>]+>", "", it["title"])})
        if page % 5 == 0:
            log("  已處理 %d 頁,事件 %d" % (page, len(events)))
    return events, seen, fail, False


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def build_scores(events):
    """具名券商的紀錄。股價從最舊事件日前約 10 個交易日開始讀。"""
    import broker_stats
    import history
    named = [e for e in events if e["broker"] != UNNAMED]
    if not named:
        return {}
    ds = history.all_dates()
    oldest = min(e["date"] for e in named)
    i = max(0, next((k for k, d in enumerate(ds) if d >= oldest), len(ds)) - 10)
    since = ds[i] if ds else oldest
    closes, dates, taiex = broker_stats.load_closes({e["code"] for e in named}, since)
    return broker_stats.scores(named, closes, dates, taiex)


def save(events, seen, now=None, base_fn=None):
    """合併 → 補 dir → 加 base → 寫 events.json、seen.json、scores.json;回傳存檔的事件。"""
    import broker_stats
    events = apply_dir(broker_stats.merge(events))
    events.sort(key=lambda e: (e["date"], e["broker"], e["code"]))
    for e in events:    # base = 發布日前一交易日收盤(同 broker_stats 的基準價);查不到就不放
        b = base_fn(e["code"], e["date"]) if base_fn else None
        if b:
            e["base"] = round(b, 2)
        else:
            e.pop("base", None)
    _dump(EVENTS, events)
    _dump(SEEN, sorted(seen))
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M")
    _dump(SCORES, {"meta": {"fetched": now, "n": len(events)}, "scores": build_scores(events)})
    return events


def check_events(events, names, base_fn=None):
    """AC-B2 檢查,回傳問題清單(空 = 通過)。"""
    import broker_stats
    bad = []
    if not isinstance(events, list) or not events:
        return ["events.json 不是非空 list"]
    for i, e in enumerate(events):
        tag = "#%d %s %s %s" % (i, e.get("date"), e.get("code"), e.get("broker"))
        for k in ("date", "code", "broker", "target", "urls"):
            if not e.get(k):
                bad.append("%s:缺 %s" % (tag, k))
        if e.get("date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e["date"])):
            bad.append("%s:date 格式不對 %s" % (tag, e["date"]))
        if e.get("code") and e["code"] not in names:
            bad.append("%s:代號不在全市場代號表" % tag)
        t = e.get("target")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
            bad.append("%s:target 不是正數 %r" % (tag, t))
        us = e.get("urls")
        if not isinstance(us, list) or not all(isinstance(u, str) and urllib.parse.urlparse(u).hostname == "money.udn.com" for u in us):
            bad.append("%s:urls 不是 money.udn.com 網址 list" % tag)
        r = ratio(base_fn, e.get("code"), e.get("date") or "", t) if isinstance(t, (int, float)) and t > 0 else None
        if r is not None and not RATIO_MIN <= r <= RATIO_MAX:
            bad.append("%s:目標價 %s 是前一交易日收盤的 %.2f 倍(合理範圍 %s～%s)" % (tag, t, r, RATIO_MIN, RATIO_MAX))
    if not bad:
        if len(broker_stats.merge(events)) != len(events):
            bad.append("有同券商＋股票＋目標價在 7 天內沒合併的事件")
        for code in ("2330", "2454"):
            n = len({e["broker"] for e in events if e["code"] == code and e["broker"] != UNNAMED})
            if n < 5:
                bad.append("%s 具名券商只有 %d 家(AC-B2 要求至少 5 家)" % (code, n))
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description="經濟日報券商目標價新聞")
    ap.add_argument("--backfill", action="store_true", help="抓到最後一頁(預設只抓前 3 頁)")
    ap.add_argument("--check", action="store_true", help="只驗證 events.json")
    a = ap.parse_args(argv)
    names = load_names()
    if a.check:
        bad = check_events(_load(EVENTS, None), names, make_base_fn())
        for b in bad[:50]:
            print("X", b)
        print("檢查%s:%d 個問題" % ("未通過" if bad else "通過", len(bad)))
        return 1 if bad else 0
    base_fn = make_base_fn()
    existing = _load(EVENTS, [])
    seen = set(_load(SEEN, []))
    events, seen, fail, page_fail = collect(fetch, names, seen, MAX_PAGES if a.backfill else DEFAULT_PAGES, existing,
                                         base_fn=base_fn)
    saved = save(events, seen, base_fn=base_fn)
    print("事件 %d(原 %d),單篇失敗 %d,已處理網址 %d,合理性過濾丟棄 %d" % (len(saved), len(existing), fail, len(seen), len(DROPPED)))
    return 1 if page_fail else 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
