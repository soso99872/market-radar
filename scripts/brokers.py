"""逐家券商目標價:經濟日報新聞標題／內文解析(純函式,不連網)。

來源是經濟日報搜尋「目標價」的新聞(抓取與合併由 T05 加在本檔)。規則式解析,不用 LLM:
  parse(title, body, names) -> [{code, broker, target, rating, dir, prev_target}, ...]
    title  新聞標題(可含 <u> 等標籤)
    body   內文純文字,可為 None;標題抽不到券商或金額時才看內文
    names  全市場 {代號: 名稱}(用 load_names() 取得),或 build_index(names) 的結果
無法明確解析(券商、股票、金額對不起來)就不產生事件。

dir 依 PRD A 第 8 點優先順序,本檔做 ① 與 ③:
  ① 新聞寫明前次目標價(例「從 6,055 元調升至 6,800 元」)→ 兩數比較,並填 prev_target
  ③ 關鍵字:調升／上修／調高／上調 → up,調降／下修／調低／下調 → down,維持／重申 → keep
  都沒有 → None。② 與我們前一筆比較,在合併事件時(T05)補。
"""
import glob
import gzip
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "history")

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
_KEEP_RE = re.compile(r"維持|重申")

_RATINGS = "強力買進|買進|買入|增持|優於大盤|跑贏大盤|超越大盤|加碼|中立|中性|持有|減碼|減持|賣出|劣於大盤|落後大盤|表現遜於大盤"
_RATING_RE = re.compile(r"[「『](" + _RATINGS + r")[」』]|(" + _RATINGS + r")(?=評等)|(?:評等|建議|給予|維持|予以)(?:至|為|於|調升至|調降至)?[「『]?(" + _RATINGS + ")")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_BAD_UNIT = r"(?![\d,.]*[美港日歐%％倍億萬月日年檔家張季點成度xX])"
# 「從 X 元…至 Y 元」「由 X 元直衝 Y 元」「從 500 元升到 725 元」
_FROM_TO = re.compile(r"[從由]\s*(" + _NUM + r")\s*元\s*([^\d，。；、]{0,8}?)\s*(" + _NUM + r")\s*元")
# 金額觸發:強觸發可省略「元」;弱觸發一定要有「元」
_STRONG = r"(?:目標價維持|目標價為|目標價|目標股價|調升至|上調至|調高至|上修至|調降至|下調至|下修至|提高至|升至|升到|降至|降到|喊到|喊|上看)"
_WEAK = r"(?:看到|看|為|至|到|達)"
_AMT_STRONG = re.compile(_STRONG + r"\s*(" + _NUM + r")" + _BAD_UNIT + r"(元)?((?:、" + _NUM + r"元?)*)")
_AMT_WEAK = re.compile(_WEAK + r"\s*(" + _NUM + r")\s*元((?:、" + _NUM + r"元?)*)")
_TP_RE = re.compile(r"目標價|目標股價")
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


def _amounts(clause, carry_tp):
    """抽出子句裡的目標價 [(位置, 目標價, 前次目標價)]。子句沒有「目標價」且前面也沒有時不抽。"""
    if not (_TP_RE.search(clause) or carry_tp):
        return []
    found, used = [], []
    for m in _FROM_TO.finditer(clause):
        found.append((m.start(), _num(m.group(3)), _num(m.group(1))))
        used.append((m.start(), m.end()))

    def free(a, b):
        return not any(a < ue and us < b for us, ue in used)

    for m in _AMT_STRONG.finditer(clause):
        if not free(m.start(), m.end()):
            continue
        if _foreign(clause, m.start()):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
        for extra in re.findall(_NUM, m.group(3) or ""):
            found.append((m.start(), _num(extra), None))
    for m in _AMT_WEAK.finditer(clause):
        if not free(m.start(), m.end()):
            continue
        if _foreign(clause, m.start()):
            continue
        used.append((m.start(), m.end()))
        found.append((m.start(), _num(m.group(1)), None))
        for extra in re.findall(_NUM, m.group(2) or ""):
            found.append((m.start(), _num(extra), None))
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


def parse(title, body, names):
    """標題優先;標題抽不到券商或金額時再用內文補。回傳 [{code, broker, target, rating, dir, prev_target}]。"""
    idx = names if isinstance(names, _Index) else build_index(names)
    title = _clean(title).replace("\n", " ")
    t_events = _analyze(title, idx)
    if t_events and all(e["broker"] != UNNAMED for e in t_events):
        return t_events
    if not body:
        return t_events
    t_stocks = list(dict.fromkeys(v for _, _, k, v in idx.find(title) if k == "stock"))
    b_events = _analyze(_clean(body), idx, title=title, fallback_stocks=t_stocks)
    if t_stocks:
        b_events = [e for e in b_events if e["code"] in t_stocks]
    result = []
    for e in t_events:
        if e["broker"] == UNNAMED:      # 內文有同檔同金額的具名券商就補上
            for b in b_events:
                if b["code"] == e["code"] and b["target"] == e["target"] and b["broker"] != UNNAMED:
                    e = dict(e, broker=b["broker"], rating=e["rating"] or b["rating"],
                             dir=e["dir"] or b["dir"], prev_target=e["prev_target"] or b["prev_target"])
                    break
        result.append(e)
    have = {e["code"] for e in result}
    result += [b for b in b_events if b["code"] not in have]
    return result
