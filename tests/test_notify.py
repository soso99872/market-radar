"""scripts/notify.py 測試:用固定資料與 mock 取代 HTTP,不打 Telegram API、不讀 data/。"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import notify  # noqa: E402

TOKEN = "123456:SECRET-TOKEN-VALUE"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999"}


def mk_latest(stars, date="2026-10-20"):
    """stars: {代號: 星等};偶數代號放 rev、其餘放 theme。"""
    rev, theme = [], []
    for c, s in stars.items():
        (rev if int(c) % 2 == 0 else theme).append({"code": c, "name": "名" + c, "stars": s})
    return {"date": date, "rev": rev, "theme": theme}


def mk_laggard(new, advantage=True, extra=()):
    lst = [{"code": c, "name": "落" + c, "topic": "ccl"} for c in list(new) + list(extra)]
    return {"date": "2026-10-20", "list": lst, "new": list(new), "advantage": advantage}


class FakeResp(object):
    def __init__(self, code=200, body=None):
        self.code, self.body = code, body if body is not None else {"ok": True}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self):
        return self.code

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class BuildMessage(unittest.TestCase):
    def test_new_5_and_4_star(self):
        latest = mk_latest({"2383": 5, "2330": 4, "1101": 4, "1102": 3})
        state = {"date": "2026-10-19", "stars": ["2330"]}
        text, ns = notify.build_message(latest, mk_laggard([]), state)
        self.assertIn("盤前雷達 2026-10-20 收盤更新", text)
        self.assertIn("新進 5★：2383 名2383", text)
        self.assertIn("新進 4★：1101 名1101", text)
        self.assertNotIn("2330 名2330", text)
        self.assertNotIn("今天沒有新名單", text)
        self.assertNotIn("首次推播", text)
        self.assertEqual(ns, {"date": "2026-10-20", "stars": ["1101", "2330", "2383"]})
        self.assertTrue(text.endswith(notify.URL))

    def test_laggard_only(self):
        latest = mk_latest({"2330": 4})
        state = {"date": "2026-10-19", "stars": ["2330"]}
        text, _ = notify.build_message(latest, mk_laggard(["6672"]), state, {"ccl": "CCL 銅箔基板"})
        self.assertIn("落後補漲新名單：6672 落6672（CCL 銅箔基板）", text)
        self.assertNotIn("新進", text)
        self.assertNotIn("今天沒有新名單", text)

    def test_nothing_new(self):
        latest = mk_latest({"2330": 4})
        state = {"date": "2026-10-19", "stars": ["2330"]}
        text, _ = notify.build_message(latest, mk_laggard([], extra=["6672"]), state)
        self.assertIn("今天沒有新名單", text)
        self.assertTrue(text.endswith(notify.URL))

    def test_first_push_lists_all(self):
        latest = mk_latest({"2330": 4, "2383": 5})
        text, ns = notify.build_message(latest, mk_laggard([]), None)
        self.assertIn("首次推播，列出全部", text)
        self.assertIn("新進 5★：2383", text)
        self.assertIn("新進 4★：2330", text)
        self.assertEqual(ns["stars"], ["2330", "2383"])

    def test_advantage_false_marks_reference(self):
        state = {"date": "d", "stars": []}
        text, _ = notify.build_message(mk_latest({}), mk_laggard(["6672"], advantage=False), state)
        self.assertIn("落後補漲新名單（僅供參考）：", text)

    def test_laggard_missing(self):
        text, _ = notify.build_message(mk_latest({}), None, {"date": "d", "stars": []})
        self.assertIn("落後補漲資料尚未產生", text)

    def test_truncate_over_15(self):
        codes = ["%04d" % (3000 + i) for i in range(20)]
        latest = mk_latest(dict((c, 4) for c in codes))
        text, _ = notify.build_message(latest, mk_laggard([]), {"date": "d", "stars": []})
        line = [l for l in text.split("\n") if l.startswith("新進 4★")][0]
        self.assertEqual(line.count("名"), 15)
        self.assertIn("…等 20 檔", line)
        self.assertLessEqual(len(text), 4096)

    def test_stars_rule_theme_overrides_rev(self):
        latest = {"date": "d", "rev": [{"code": "2330", "name": "a", "stars": 5}],
                  "theme": [{"code": "2330", "name": "a", "stars": 2}, {"code": "1101", "name": "b"}]}
        self.assertEqual(notify.star_map(latest), {"2330": 2, "1101": 1})


    def test_laggard_date_mismatch_not_pushed(self):   # laggard.json 是舊日期:不把它的 new 當今日名單
        lg = mk_laggard(["6672"])
        lg["date"] = "2026-10-19"
        text, _ = notify.build_message(mk_latest({}), lg, {"date": "d", "stars": []})
        self.assertIn("落後補漲資料未更新", text)
        self.assertNotIn("6672", text)
        self.assertNotIn("落後補漲新名單", text)
        self.assertIn("今天沒有新名單", text)   # 沒有任何新名單時照樣標示

    def test_laggard_date_match_still_pushed(self):
        text, _ = notify.build_message(mk_latest({}), mk_laggard(["6672"]), {"date": "d", "stars": []})
        self.assertIn("落後補漲新名單：6672", text)
        self.assertNotIn("未更新", text)


class SiteUrl(unittest.TestCase):
    def reload_with(self, env):
        import importlib
        with mock.patch.dict(os.environ, env):
            os.environ.pop("SITE_URL", None) if "SITE_URL" not in env else None
            importlib.reload(notify)
            return notify.URL

    def tearDown(self):
        import importlib
        importlib.reload(notify)

    def test_empty_env_uses_default(self):   # GitHub 變數未設時 workflow 會傳空字串
        self.assertEqual(self.reload_with({"SITE_URL": ""}), "https://stock-market-radar.pages.dev/radar")

    def test_unset_env_uses_default(self):
        self.assertEqual(self.reload_with({}), "https://stock-market-radar.pages.dev/radar")

    def test_custom_env(self):
        self.assertEqual(self.reload_with({"SITE_URL": "https://example.com/"}), "https://example.com/radar")


class Send(unittest.TestCase):
    def test_payload_without_thread(self):
        seen = {}

        def op(req, timeout=None):
            seen["data"] = json.loads(req.data.decode("utf-8"))
            return FakeResp()
        self.assertEqual(notify.send("hi", ENV, op), (True, ""))
        self.assertEqual(seen["data"], {"chat_id": "-100999", "text": "hi"})

    def test_payload_with_thread(self):
        seen = {}

        def op(req, timeout=None):
            seen["data"] = json.loads(req.data.decode("utf-8"))
            return FakeResp()
        env = dict(ENV, TELEGRAM_THREAD_ID="42")
        notify.send("hi", env, op)
        self.assertEqual(seen["data"]["message_thread_id"], 42)

    def test_failures_return_false_and_hide_token(self):
        def boom(req, timeout=None):
            raise OSError("cannot reach https://api.telegram.org/bot%s/sendMessage" % TOKEN)
        ok, err = notify.send("hi", ENV, boom)
        self.assertFalse(ok)
        self.assertNotIn(TOKEN, err)
        self.assertFalse(notify.send("hi", ENV, lambda r, timeout=None: FakeResp(500))[0])
        ok, err = notify.send("hi", ENV, lambda r, timeout=None: FakeResp(200, {"ok": False, "description": "bad " + TOKEN}))
        self.assertFalse(ok)
        self.assertNotIn(TOKEN, err)


class Main(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.paths = {}
        for k in ("LATEST", "LAGGARD", "TOPICS", "STATE"):
            self.paths[k] = os.path.join(self.tmp, k.lower() + ".json")
        self.patches = [mock.patch.object(notify, k, v) for k, v in self.paths.items()]
        for p in self.patches:
            p.start()
        self.write("LATEST", mk_latest({"2330": 4}))
        self.write("LAGGARD", mk_laggard(["6672"]))

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def write(self, k, obj):
        with open(self.paths[k], "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def state(self):
        p = self.paths["STATE"]
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def run_main(self, argv, env, opener=None):
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            code = notify.main(argv, env, opener)
        return code, out.getvalue()

    def test_send_success_updates_state(self):
        calls = []
        code, _ = self.run_main([], ENV, lambda r, timeout=None: calls.append(1) or FakeResp())
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.state(), {"date": "2026-10-20", "stars": ["2330"]})

    def test_same_date_not_resent(self):
        self.write("STATE", {"date": "2026-10-20", "stars": ["2330"]})
        calls = []
        code, out = self.run_main([], ENV, lambda r, timeout=None: calls.append(1) or FakeResp())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("已推播過", out)

    def test_no_token_exit0_state_untouched(self):
        calls = []
        code, out = self.run_main([], {}, lambda r, timeout=None: calls.append(1) or FakeResp())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("未設定 TELEGRAM_BOT_TOKEN／TELEGRAM_CHAT_ID，略過推播", out)
        self.assertIsNone(self.state())

    def test_api_failure_exit0_state_untouched_no_token_in_log(self):
        def boom(req, timeout=None):
            raise OSError("fail " + req.full_url)
        code, out = self.run_main([], ENV, boom)
        self.assertEqual(code, 0)
        self.assertIsNone(self.state())
        self.assertNotIn(TOKEN, out)
        self.assertIn("warning", out)

    def test_dry_run_prints_and_no_side_effects(self):
        calls = []
        code, out = self.run_main(["--dry-run"], ENV, lambda r, timeout=None: calls.append(1) or FakeResp())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("盤前雷達 2026-10-20", out)
        self.assertIsNone(self.state())

    def test_laggard_file_missing(self):
        os.remove(self.paths["LAGGARD"])
        _, out = self.run_main(["--dry-run"], {})
        self.assertIn("落後補漲資料尚未產生", out)


if __name__ == "__main__":
    unittest.main()
