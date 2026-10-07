/* 開啟頁面時的即時更新:證交所若已公布比網站資料更新的收盤行情,直接在瀏覽器讀官方資料
   (證交所 API 允許跨網域讀取;櫃買中心不允許,所以上櫃股要等排程更新)。不經過任何 AI,不耗 token。 */
(function () {
  "use strict";
  var MR = window.MR;
  var CACHE = "live.mi.";

  function taipeiNow() {
    var d = new Date(Date.now() + 8 * 3600e3);
    return { iso: d.toISOString().slice(0, 10), hour: d.getUTCHours() + d.getUTCMinutes() / 60, dow: d.getUTCDay() };
  }

  function num(s) {
    var v = parseFloat(String(s).replace(/,/g, ""));
    return isNaN(v) ? null : v;
  }

  function parseMI(j) {
    if (!j || j.stat !== "OK") return null;
    var out = {};
    (j.tables || []).forEach(function (t) {
      var f = t.fields || [];
      if (f.indexOf("證券代號") < 0 || f.indexOf("收盤價") < 0) return;
      var ix = {};
      ["證券代號", "證券名稱", "收盤價", "漲跌(+/-)", "漲跌價差", "成交金額"].forEach(function (k) { ix[k] = f.indexOf(k); });
      (t.data || []).forEach(function (r) {
        var c = String(r[ix["證券代號"]]).trim();
        if (!/^[1-9]\d{3}$/.test(c)) return;
        var close = num(r[ix["收盤價"]]);
        if (!close) return;
        var diff = num(r[ix["漲跌價差"]]) || 0;
        if (String(r[ix["漲跌(+/-)"]]).indexOf("-") >= 0) diff = -diff;
        var prev = close - diff;
        out[c] = [String(r[ix["證券名稱"]]).trim(), close, prev ? Math.round(diff / prev * 10000) / 100 : 0,
          Math.round((num(r[ix["成交金額"]]) || 0) / 1e6) / 100];
      });
    });
    return Object.keys(out).length ? out : null;
  }

  // 網站資料日之後、到今天為止的交易日候選(新到舊);今天要 14:00 收盤資料出來後才試
  function candidates(siteDate) {
    var now = taipeiNow(), list = [];
    var d = new Date(now.iso + "T00:00:00Z");
    for (var i = 0; i < 5 && list.length < 3; i++) {
      var iso = d.toISOString().slice(0, 10), dow = d.getUTCDay();
      if (iso <= siteDate) break;
      if (dow > 0 && dow < 6 && !(iso === now.iso && now.hour < 14)) list.push(iso);
      d.setUTCDate(d.getUTCDate() - 1);
    }
    return list;
  }

  MR.fetchLive = function (siteDate) {
    var cands = candidates(siteDate);
    MR._liveState = cands.length ? "checking" : "synced";
    function tryOne(i) {
      if (i >= cands.length) { MR._liveState = "none"; return Promise.resolve(null); }
      var iso = cands[i];
      try {
        var hit = sessionStorage.getItem(CACHE + iso);
        if (hit) { MR._liveState = "live"; return Promise.resolve({ date: iso, s: JSON.parse(hit) }); }
      } catch (e) {}
      var url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=" + iso.replace(/-/g, "") + "&type=ALLBUT0999&response=json";
      return fetch(url).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
        var s = parseMI(j);
        if (!s) return tryOne(i + 1);
        try { sessionStorage.setItem(CACHE + iso, JSON.stringify(s)); } catch (e) {}
        MR._liveState = "live";
        return { date: iso, s: s };
      }).catch(function () { return tryOne(i + 1); });
    }
    return tryOne(0);
  };

  MR.liveStatus = function (live, siteDate) {
    if (live) return '<b style="color:var(--accent)">已即時更新</b> 上市股價為證交所 ' + MR.md(live.date) + " 官方收盤(上櫃、法人與排名待排程更新)";
    var st = MR._liveState;
    if (st === "checking") return "檢查證交所最新資料…";
    if (st === "none") return "證交所尚未公布更新的收盤資料";
    return "已是最新資料";
  };

  MR.patchPrices = function (root, live) {
    var st = root.querySelector("#live-status");
    if (st) st.innerHTML = MR.liveStatus(live);
    if (!live) return;
    Array.prototype.forEach.call(root.querySelectorAll("[data-px]"), function (el) {
      var r = live.s[el.getAttribute("data-px")];
      if (r) el.innerHTML = r[1] + " " + MR.pct(r[2]) + '<span class="lv">' + MR.md(live.date) + "</span>";
    });
  };

  // 用排程算好的門檻(前 20 日均量、前 60 日高低點、前 250 日高點)判斷今天是否爆量突破
  MR.liveBreakouts = function (live, th) {
    if (!live || !th || live.date <= th.date) return [];
    var out = [];
    Object.keys(th.s).forEach(function (c) {
      var r = live.s[c], t = th.s[c];
      if (!r || !t[0]) return;
      var close = r[1], chg = r[2], value = r[3];
      var avg20 = t[0], mx60 = t[1], mn60 = t[2], mx250 = t[3], yoy3 = t[5];
      if (value < th.min_value || value < th.surge * avg20 || chg < 5) return;
      if (close < mx60 || mx60 / mn60 - 1 > 0.35 || close < mx250) return;
      var surge = Math.round(value / avg20 * 10) / 10, revOk = yoy3 != null && yoy3 >= 20;
      out.push({
        code: c, name: r[0] || t[6], close: close, chg: chg, surge: surge, day_chg: chg, yoy3: yoy3, rev_ok: revOk,
        since: null, days_ago: 0, low_vol: false, themes: [],
        why: [MR.md(live.date) + " 爆量 " + Math.round(surge) + " 倍、漲 " + MR.sign(chg, 1) + "%,突破整理並創 52 週新高(官方收盤即時判斷)",
          yoy3 == null ? "無月營收資料" : "近 3 個月營收平均年增 " + MR.sign(yoy3, 0) + "%" + (revOk ? "" : "(未達 20%,歷史上效果較差)")]
      });
    });
    out.sort(function (a, b) { return (b.rev_ok - a.rev_ok) || (b.surge - a.surge); });
    return out;
  };
})();
