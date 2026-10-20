"""Telegram 推播:資料更新後,把新進 4★／5★ 與落後補漲新名單送到群組的「股票」話題。

環境變數:TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID(群組 id)、選填 TELEGRAM_THREAD_ID(話題 id)。
未設定就略過、API 失敗只印警告,結束碼一律 0,不讓排程失敗。

用法:python scripts/notify.py            # 正式推播
      python scripts/notify.py --dry-run # 只印訊息,不送、不改狀態檔
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "radar", "latest.json")
LAGGARD = os.path.join(ROOT, "data", "radar", "laggard.json")
TOPICS = os.path.join(ROOT, "data", "sectors", "topics.json")
STATE = os.path.join(ROOT, "data", "radar", "notify_state.json")
SITE = os.environ.get("SITE_URL", "https://stock-market-radar.pages.dev").rstrip("/")   # 換網域只要改 GitHub repo 變數 SITE_URL
URL = SITE + "/radar"
MAX_PER_SECTION = 15
MAX_LEN = 4096


def _read(path):
    """讀 JSON,檔案不存在回傳 None。"""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def star_map(latest):
    """代號 → 星等。與 radar.html 的 starOf() 相同:rev、theme 兩份名單,後者覆蓋前者,沒星等當 1★。"""
    stars = {}
    for x in (latest.get("rev") or []) + (latest.get("theme") or []):
        stars[x["code"]] = x.get("stars") or 1
    return stars


def name_map(latest):
    names = {}
    for key in ("rev", "theme", "rank"):
        for x in latest.get(key) or []:
            names.setdefault(x["code"], x.get("name", ""))
    return names


def _fmt_list(items):
    """items 為已格式化字串;超過上限截斷並註明總檔數。"""
    shown = items[:MAX_PER_SECTION]
    s = "、".join(shown)
    if len(items) > MAX_PER_SECTION:
        s += "…等 %d 檔" % len(items)
    return s


def build_message(latest, laggard, state, topic_names=None):
    """純函式。回傳 (訊息文字, 新狀態)。
    latest:latest.json;laggard:laggard.json 或 None(尚未產生);state:狀態檔內容或 None(首次)。
    topic_names:題材 id → 中文名(laggard 名單沒帶 topic_name 時使用)。"""
    topic_names = topic_names or {}
    stars = star_map(latest)
    names = name_map(latest)
    today = {c for c, s in stars.items() if s >= 4}
    first = state is None
    prev = set() if first else set(state.get("stars") or [])
    new = sorted(today - prev)
    new5 = [c for c in new if stars[c] >= 5]
    new4 = [c for c in new if stars[c] == 4]

    def lab(c):
        return ("%s %s" % (c, names.get(c, ""))).strip()

    lines = ["盤前雷達 %s 收盤更新" % latest["date"]]
    if first:
        lines.append("首次推播，列出全部")
    if new5:
        lines.append("新進 5★：" + _fmt_list([lab(c) for c in new5]))
    if new4:
        lines.append("新進 4★：" + _fmt_list([lab(c) for c in new4]))

    lag_new = []
    if laggard is None:
        lines.append("落後補漲資料尚未產生")
    else:
        by_code = {}
        for x in laggard.get("list") or []:
            by_code.setdefault(x["code"], x)
        for c in laggard.get("new") or []:
            x = by_code.get(c, {"code": c})
            nm = x.get("name") or names.get(c, "")
            t = x.get("topic_name") or topic_names.get(x.get("topic"), "") or x.get("topic") or ""
            s = ("%s %s" % (c, nm)).strip()
            lag_new.append(s + ("（%s）" % t if t else ""))
        if lag_new:
            title = "落後補漲新名單" + ("" if laggard.get("advantage") else "（僅供參考）")
            lines.append(title + "：" + _fmt_list(lag_new))

    if not new5 and not new4 and not lag_new:
        lines.append("今天沒有新名單")
    lines.append(URL)
    text = "\n".join(lines)
    if len(text) > MAX_LEN:  # 保底:每段已限 15 檔,正常不會到這裡
        text = text[:MAX_LEN - len(URL) - 2] + "…\n" + URL
    return text, {"date": latest["date"], "stars": sorted(today)}


def _mask(msg, token):
    return str(msg).replace(token, "***") if token else str(msg)


def send(text, env, opener=None):
    """呼叫 sendMessage。回傳 (成功與否, 錯誤訊息);錯誤訊息已遮掉 token。"""
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    payload = {"chat_id": env.get("TELEGRAM_CHAT_ID", ""), "text": text}
    thread = (env.get("TELEGRAM_THREAD_ID") or "").strip()
    if thread:
        payload["message_thread_id"] = int(thread) if thread.lstrip("-").isdigit() else thread
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=30) as r:
            code = r.getcode()
            body = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # 網路、HTTP 錯誤、JSON 解析失敗
        return False, _mask("%s: %s" % (type(e).__name__, e), token)
    if code != 200:
        return False, "HTTP %s" % code
    if not body.get("ok"):
        return False, _mask("ok=false %s" % body.get("description", ""), token)
    return True, ""


def _save_state(state):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
        f.write("\n")


def main(argv=None, env=None, opener=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    dry = "--dry-run" in argv
    latest = _read(LATEST)
    if not latest:
        print("找不到 latest.json,略過推播")
        return 0
    state = _read(STATE)
    if not dry and state and state.get("date") == latest["date"]:
        print("資料日期 %s 已推播過,略過" % latest["date"])
        return 0
    topic_names = {t["id"]: t["name"] for t in (_read(TOPICS) or [])}
    text, new_state = build_message(latest, _read(LAGGARD), state, topic_names)
    if dry:
        print(text)
        return 0
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
        print("未設定 TELEGRAM_BOT_TOKEN／TELEGRAM_CHAT_ID，略過推播")
        return 0
    ok, err = send(text, env, opener)
    if not ok:
        print("::warning::Telegram 推播失敗:%s" % err)
        return 0
    _save_state(new_state)
    print("已推播 %s,%d 字" % (latest["date"], len(text)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
