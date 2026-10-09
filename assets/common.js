/* 各頁共用:格式化工具、漲跌顏色慣例、個股詳情面板(MR.openStock) */
(function () {
  "use strict";
  var MR = window.MR = {};

  MR.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var esc = MR.esc;
  MR.dir = function (v) { return v > 0 ? "up" : v < 0 ? "down" : "flat"; };
  MR.sign = function (v, d) { return v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d); };
  MR.yi = function (v) {
    if (v == null) return '<span class="flat">—</span>';
    return '<span class="' + MR.dir(v) + '">' + MR.sign(v, Math.abs(v) >= 100 ? 1 : 2) + " 億</span>";
  };
  MR.pct = function (v) {
    return v == null ? '<span class="flat">—</span>' : '<span class="' + MR.dir(v) + '">' + MR.sign(v, 2) + "%</span>";
  };
  MR.md = function (iso) { return iso.slice(5).replace("-", "/"); };
  MR.json = function (url) {
    return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  };

  // 漲跌顏色慣例(各頁共用同一個設定)
  MR.setupConv = function () {
    function setConv(c) {
      document.documentElement.setAttribute("data-convention", c);
      document.getElementById("conv-tw").setAttribute("aria-pressed", c === "tw");
      document.getElementById("conv-us").setAttribute("aria-pressed", c === "us");
      try { localStorage.setItem("conv", c); } catch (e) {}
    }
    var saved = "tw";
    try { saved = localStorage.getItem("conv") || "tw"; } catch (e) {}
    setConv(saved);
    document.getElementById("conv-tw").onclick = function () { setConv("tw"); };
    document.getElementById("conv-us").onclick = function () { setConv("us"); };
  };

  // 訊號統計(個股面板會用到),只載一次
  var statsP = null;
  MR.stats = function () {
    if (!statsP) statsP = MR.json("data/signals/stats.json").catch(function () { return null; });
    return statsP;
  };
  // 個股基本資料(scripts/profile.py),只載一次
  var profP = null;
  MR.profile = function () {
    if (!profP) profP = MR.json("data/profile/latest.json").catch(function () { return {}; });
    return profP;
  };

  // ---- 星等評級(依 scripts/explosion_study.py 回測:分層 + 陷阱扣分) ----
  var TIER_NAME = { A: "營收＋動能＋題材", B: "營收＋動能或題材其一", C: "只有營收(最早期)", D: "題材動能、營收未跟上" };
  MR.stars = function (n) {
    n = n || 1;
    return '<span class="stars s' + n + '" title="評級 ' + n + ' 顆星(依歷史回測,不是保證)" aria-label="' + n + ' 顆星">' +
      "★★★★★".slice(0, n) + "<i>" + "★★★★★".slice(n) + "</i></span>";
  };
  MR.ratingLine = function (r) {
    r = r || { stars: 1 };
    var why = r.tier ? r.tier + " 層:" + TIER_NAME[r.tier] : "不在起漲雷達任何名單";
    return MR.stars(r.stars) + '<span class="rt-why">' + esc(why) + (r.traps && r.traps.length ? ",有陷阱:" + esc(r.traps.join("、")) + "(扣 1 顆)" : "") + "</span>";
  };

  // ---- 自選股:存在這個瀏覽器(localStorage),換裝置用匯出/匯入。提醒 = 和上次「已看過」時的狀態比較 ----
  var WKEY = "mr.watch.v1";
  MR.watch = {
    load: function () {
      try { var s = JSON.parse(localStorage.getItem(WKEY) || "null"); if (s && s.codes) return s; } catch (e) {}
      return { codes: [], alerts: {}, seen: {} };
    },
    save: function (s) { try { localStorage.setItem(WKEY, JSON.stringify(s)); } catch (e) {} },
    has: function (c) { return MR.watch.load().codes.indexOf(c) >= 0; },
    // 加入時記下當下狀態,之後的變化才算「新」
    add: function (c, row) {
      var s = MR.watch.load();
      if (s.codes.indexOf(c) < 0) s.codes.push(c);
      if (row) s.seen[c] = MR.watch.snap(row);
      MR.watch.save(s);
    },
    remove: function (c) {
      var s = MR.watch.load();
      s.codes = s.codes.filter(function (x) { return x !== c; });
      delete s.alerts[c]; delete s.seen[c];
      MR.watch.save(s);
    },
    snap: function (x) {
      var h = x[12] || {};
      return { stars: x[1], rev: x[9], above: h.above_ma60, traps: (x[11] || []).slice() };
    },
    // 回傳 [{t: 文字, k: "up"|"down"|"info"}];x 是 index.json 的一列
    changes: function (c, x, s) {
      s = s || MR.watch.load();
      var out = [], o = s.seen[c], h = x[12] || {}, a = s.alerts[c] || {};
      if (o) {
        if (o.stars !== x[1]) out.push({ t: "評級 " + o.stars + "★ → " + x[1] + "★", k: x[1] > o.stars ? "up" : "down" });
        if (x[9] && x[9] !== o.rev) out.push({ t: "公布 " + x[9].slice(5).replace(/^0/, "") + " 月營收,年增 " + MR.sign(x[7], 0) + "%", k: "info" });
        if (o.above === true && h.above_ma60 === false) out.push({ t: "跌破季線", k: "down" });
        if (o.above === false && h.above_ma60 === true) out.push({ t: "站上季線", k: "up" });
        (x[11] || []).forEach(function (tr) { if ((o.traps || []).indexOf(tr) < 0) out.push({ t: "出現陷阱:" + tr, k: "down" }); });
      }
      if (a.up != null && x[3] >= a.up) out.push({ t: "到價:≥ " + a.up, k: "up" });
      if (a.dn != null && x[3] <= a.dn) out.push({ t: "到價:≤ " + a.dn, k: "down" });
      return out;
    },
    seenAll: function (I) {
      var s = MR.watch.load();
      s.codes.forEach(function (c) { if (I.s[c]) s.seen[c] = MR.watch.snap(I.s[c]); });
      MR.watch.save(s);
    }
  };
  MR.watchBtn = function (code) {
    var on = MR.watch.has(code);
    return '<button type="button" class="wbtn' + (on ? " on" : "") + '" data-watch="' + esc(code) + '" aria-pressed="' + on + '">' + (on ? "★ 已在自選" : "☆ 加入自選") + "</button>";
  };
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-watch]");
    if (!b) return;
    e.preventDefault();
    var c = b.getAttribute("data-watch");
    if (MR.watch.has(c)) { MR.watch.remove(c); finish(); }
    else MR.index().then(function (I) { MR.watch.add(c, I && I.s[c]); finish(); });
    function finish() {
      Array.prototype.forEach.call(document.querySelectorAll('[data-watch="' + c + '"]'), function (x) { x.outerHTML = MR.watchBtn(c); });
      navBadge();
      document.dispatchEvent(new CustomEvent("mr-watch"));
    }
  });
  // 導覽列「我的自選」旁標出有變化的檔數
  function navBadge() {
    var a = document.querySelector('.nav a[href="my.html"]');
    if (!a) return;
    var s = MR.watch.load();
    if (!s.codes.length) { a.textContent = "我的自選"; return; }
    MR.index().then(function (I) {
      if (!I) return;
      var n = s.codes.filter(function (c) { return I.s[c] && MR.watch.changes(c, I.s[c], s).length; }).length;
      a.innerHTML = "我的自選" + (n ? '<span class="nbadge" title="' + n + ' 檔有變化">' + n + "</span>" : "");
    });
  }
  MR.navBadge = navBadge;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", navBadge); else navBadge();

  // ---- 今天先看這 10 檔:data/radar/picks.json(排序規則在 scripts/radar.py write_picks) ----
  MR.picks = function () { return MR.json("data/radar/picks.json"); };
  MR.picksHtml = function (P, more) {
    if (!P || !P.top || !P.top.length) return "";
    var c = P.curve || {}, k = c["4★ 以上"], all = c["全部可交易股票"];
    function why(x) {
      var w = [];
      if (x.rev_month) w.push(x.rev_month.slice(5).replace(/^0/, "") + " 月營收年增 " + MR.sign(x.yoy, 0) + "%");
      if (x.ret60 != null) w.push("60 日 " + MR.sign(x.ret60, 0) + "%");
      if (x.rev_new) w.push("新公告");
      if (x.value20 != null && x.value20 < P.liq) w.push("成交偏少");
      if (x.risk && x.risk.length) w.push("⚠ " + x.risk.join("、"));
      return w.join(" · ");
    }
    var card = function (x) {
      return '<button type="button" class="pk" data-stock="' + esc(x.code) + '">' + '<span class="pk-h">' + MR.stars(x.stars) +
        '<span class="pk-px" data-px="' + esc(x.code) + '">' + esc(x.close) + " " + MR.pct(x.chg) + "</span></span>" +
        '<span class="pk-n"><b>' + esc(x.code) + "</b>" + esc(x.name) + (x.ind ? '<small>' + esc(x.ind) + "</small>" : "") + "</span>" +
        '<span class="pk-w">' + esc(why(x)) + "</span></button>";
    };
    var rest = P.rest || [];
    return '<section class="picks"><div class="pk-top"><h2>今天先看這 ' + P.top.length + " 檔</h2>" +
      "<span>起漲雷達 4★ 以上共 " + P.n + " 檔,依 星等 → 本月新公告 → 好進出(20 日均成交 ≥ " + P.liq + " 億)→ 近 3 月營收年增 排序" + (P.ind_cap ? ",同一產業最多 " + P.ind_cap + " 檔" : "") + ";處置中的不列、有財務地雷的排後面,點了看健檢</span></div>" +
      '<div class="pk-list">' + P.top.map(card).join("") + "</div>" +
      (rest.length ? '<details class="pk-rest"><summary>其餘 ' + rest.length + " 檔 4★ 以上</summary>" + '<div class="pk-list">' + rest.map(card).join("") + "</div></details>" : "") +
      '<p class="pk-foot">' + (k ? "回測:每月買全部 4★ 以上、持有一個月,年化 " + MR.sign(k.cagr, 0) + "%、最大回撤 " + k.mdd + "%(同期全部股票 " + MR.sign(all && all.cagr, 0) + "%)。" : "") +
      "建議分散買、單檔不超過可投入金額的 1/10;評級是統計機率,不是保證。" + (more ? ' <a href="radar.html">看起漲雷達 →</a>' : "") + "</p></section>";
  };

  // 查詢索引(全部股票,scripts/signals.py write_index),只載一次
  var idxP = null;
  MR.index = function () {
    if (!idxP) idxP = MR.json("data/stocks/index.json").catch(function () { return null; });
    return idxP;
  };

  MR.gradeTag = function (g) {
    var cls = { "強": "g3", "中": "g2", "反向": "gneg", "弱": "g1" }[g] || "g0";
    return '<span class="grade ' + cls + '" title="證據強度">證據' + esc(g) + "</span>";
  };

  // ---- 個股詳情面板 ----
  var dlg = null;
  function ensureDialog() {
    if (dlg) return dlg;
    dlg = document.createElement("dialog");
    dlg.className = "sheet";
    dlg.setAttribute("aria-labelledby", "stk-title");
    document.body.appendChild(dlg);
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg || e.target.closest("[data-close]")) dlg.close();
    });
    return dlg;
  }

  function sma(vals, n) {
    return vals.map(function (_, i) {
      if (i < n - 1) return null;
      var s = 0;
      for (var k = i - n + 1; k <= i; k++) s += vals[k];
      return s / n;
    });
  }

  function kchart(doc, names, grades) {
    var rows = doc.rows, n = rows.length;
    if (n < 2) return "";
    var W = 640, H1 = 180, GAP = 10, H2 = 64, H = H1 + GAP + H2, bw = W / n;
    var hi = Math.max.apply(null, rows.map(function (r) { return r[2]; }));
    var lo = Math.min.apply(null, rows.map(function (r) { return r[3]; }));
    var pad = (hi - lo) * 0.06 || 1;
    hi += pad; lo -= pad * 1.6; // 下方留空間給訊號標記
    function y(p) { return (hi - p) / (hi - lo) * H1; }
    var out = [];
    rows.forEach(function (r, i) {
      var x = i * bw + bw / 2, up = r[4] >= r[1], col = "var(--" + (up ? "up" : "down") + ")";
      var top = y(Math.max(r[1], r[4])), bot = y(Math.min(r[1], r[4]));
      out.push('<line x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="' + y(r[2]).toFixed(1) + '" y2="' + y(r[3]).toFixed(1) +
        '" stroke="' + col + '" stroke-width="1" vector-effect="non-scaling-stroke"/>');
      out.push('<rect x="' + (i * bw + bw * 0.15).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + (bw * 0.7).toFixed(1) +
        '" height="' + Math.max(bot - top, 0.8).toFixed(1) + '" fill="' + col + '"><title>' + MR.md(r[0]) + " 開 " + r[1] + " 高 " + r[2] +
        " 低 " + r[3] + " 收 " + r[4] + "</title></rect>");
    });
    var ma = sma(rows.map(function (r) { return r[4]; }), 20);
    var pts = ma.map(function (v, i) { return v == null ? null : (i * bw + bw / 2).toFixed(1) + "," + y(v).toFixed(1); }).filter(Boolean);
    if (pts.length > 1) out.push('<polyline points="' + pts.join(" ") + '" fill="none" stroke="var(--accent)" stroke-width="1.3" vector-effect="non-scaling-stroke" opacity=".9"/>');
    // 訊號標記
    var idx = {};
    rows.forEach(function (r, i) { idx[r[0]] = i; });
    // 只標證據強度「中」以上或「反向」的訊號,避免頻繁的弱訊號把圖洗滿
    (doc.signals || []).forEach(function (m) {
      var i = idx[m[0]], g = grades[m[1]];
      if (i == null || !(g === "強" || g === "中" || g === "反向")) return;
      var x = i * bw + bw / 2, yy = y(rows[i][3]) + 7;
      out.push('<path d="M' + x.toFixed(1) + " " + yy.toFixed(1) + " l-4 7 h8 z\" fill=\"var(--accent)\"><title>" +
        MR.md(m[0]) + " " + esc((names[m[1]] || m[1])) + "</title></path>");
    });
    // 法人淨買賣超柱
    var nets = rows.map(function (r) { return (r[6] || 0) + (r[7] || 0) + (r[8] || 0); });
    var mx = Math.max.apply(null, nets.map(Math.abs)) || 1, mid = H1 + GAP + H2 / 2;
    out.push('<line x1="0" x2="' + W + '" y1="' + mid + '" y2="' + mid + '" stroke="var(--line)"/>');
    nets.forEach(function (v, i) {
      var h = Math.abs(v) / mx * (H2 / 2 - 2);
      out.push('<rect x="' + (i * bw + bw * 0.15).toFixed(1) + '" y="' + (v >= 0 ? mid - h : mid).toFixed(1) + '" width="' + (bw * 0.7).toFixed(1) +
        '" height="' + Math.max(h, 0.6).toFixed(1) + '" fill="var(--' + (v >= 0 ? "up" : "down") + ')" opacity=".85"><title>' +
        MR.md(rows[i][0]) + " 法人 " + MR.sign(v, 2) + " 億</title></rect>");
    });
    return '<div class="kchart"><div class="klegend"><span><i style="background:var(--accent)"></i>20 日均線</span>' +
      '<span>▲ 證據中以上的訊號</span><span>下方:三大法人每日淨買賣超</span></div>' +
      '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" style="height:' + Math.round(H * 0.62) + 'px" role="img" aria-label="近 ' + n + ' 日 K 線與法人買賣超">' +
      out.join("") + '</svg><div class="cap"><span>' + MR.md(rows[0][0]) + "</span><span>" + n + " 個交易日</span><span>" + MR.md(rows[n - 1][0]) + "</span></div></div>";
  }

  // 模型合理價:公式固定,把每一步算式攤開讓人可以自己驗算
  function fvHtml(doc) {
    var ex = doc.extra || {}, e = ex.fv, px = doc.summary.close;
    if (!e) return '<div class="fvbox"><h4>估值</h4><p class="flat" style="font-size:13px;margin:0">資料不足(需要至少 24 個月的本益比或淨值比歷史),不估算。</p></div>';
    var cls = e.status === "低估" ? "up" : e.status === "高估" ? "down" : "flat";
    var l = (e.low * 0.8), span = (e.high * 1.2 - l) || 1;
    function at(v) { return Math.max(0, Math.min(100, (v - l) / span * 100)).toFixed(1) + "%"; }
    var how = e.method === "pe"
      ? "近四季 EPS " + e.eps + " 元(股價 ÷ 本益比 " + e.pe + ")× 營收動能 " + e.growth + " 倍 = 預估 EPS <b>" + e.feps + "</b> 元;" +
        "× 過去 " + e.n + " 個月本益比中位數 " + e.band[1] + " 倍 = <b>" + e.fair + "</b> 元。合理區間用第 25~75 百分位(" + e.band[0] + "~" + e.band[2] + " 倍)。"
      : "公司虧損或本益比過高,改用淨值比:每股淨值 " + e.bvps + " 元 × 過去 " + e.n + " 個月淨值比中位數 " + e.band[1] + " 倍 = <b>" + e.fair + "</b> 元。";
    var w = e.fwd, t = e.tgt, fwdHtml = "", pj = e.proj;
    // 沒有分析師預估:用最新營收與最新一季淨利率自行推估未來 12 個月 EPS(scripts/radar.py run_rate_eps)
    if (!w && pj) {
      var pc = pj.status === "低估" ? "up" : pj.status === "高估" ? "down" : "flat";
      fwdHtml = '<div class="fvbox"><h4>前瞻估值 · 自行推估(沒有分析師預估)</h4><div class="fvgrid">' +
        "<div><span>未來 12 月 EPS</span><b>" + pj.eps + "</b></div><div><span>前瞻本益比</span><b>" + pj.pe + " 倍</b></div>" +
        "<div><span>前瞻合理價</span><b>" + pj.fair + '</b></div><div><span>前瞻空間</span><b class="' + MR.dir(pj.up) + '">' + MR.sign(pj.up, 1) + "%</b></div>" +
        '<div><span>前瞻評價</span><b class="' + pc + '">' + pj.status + "</b></div></div>" +
        '<p class="fvhow">近 3 月營收 × 4 = 年化 ' + pj.rev12 + " 億 × 最新一季(" + esc(pj.p) + ")稅後淨利率 " + pj.nm + "% ÷ 股數 = 未來 12 個月 EPS <b>" + pj.eps +
        "</b> 元;× 自身過去本益比中位數 " + pj.band[1] + " 倍 = <b>" + pj.fair + "</b> 元,合理區間 " + pj.low + " ~ " + pj.high + "(" + pj.band[0] + "~" + pj.band[2] + " 倍)。</p>" +
        (pj.g_eps ? '<p class="fvhow"><b>成長情境</b>:如果近 3 月營收年增 ' + MR.sign(pj.g_yoy, 0) + "% 再延續 12 個月,營收 " + pj.g_rev12 + " 億 × 同樣淨利率 = EPS <b>" + pj.g_eps +
          "</b> 元,× " + pj.band[1] + " 倍 = <b>" + pj.g_fair + "</b> 元(空間 " + MR.sign(pj.g_up, 1) + "%)。</p>" : "") +
        '<p class="fvhow">上面是「維持現狀」:假設接下來 12 個月維持目前的營收與獲利率。成長情境假設成長率延續,實際常會放緩。單季淨利率可能有一次性損益。這個算法是 2026-10 新增,尚未回測。</p>' +
        (t ? '<p class="fvhow">分析師平均目標價 <b>' + t.mean + "</b>,相對現價 " + MR.sign(t.up, 1) + "%。</p>" : "") + "</div>";
    }
    if (w || (t && !pj)) {
      var wcls = w ? (w.status === "低估" ? "up" : w.status === "高估" ? "down" : "flat") : "flat";
      fwdHtml = '<div class="fvbox"><h4>前瞻估值 · 依分析師共識預估</h4>' +
        (w ? '<div class="fvgrid"><div><span>未來 12 月 EPS</span><b>' + w.eps + "</b></div>" +
          "<div><span>前瞻本益比</span><b>" + w.pe + " 倍</b></div>" +
          "<div><span>前瞻合理價</span><b>" + w.fair + "</b></div>" +
          '<div><span>前瞻空間</span><b class="' + MR.dir(w.up) + '">' + MR.sign(w.up, 1) + "%</b></div>" +
          '<div><span>前瞻評價</span><b class="' + wcls + '">' + w.status + "</b></div></div>" +
          '<p class="fvhow">今年 EPS 預估 ' + (w.eps0 == null ? "—" : w.eps0) + "、明年 " + w.eps1 + "(" + (w.n || "?") + " 位分析師),依月份加權成未來 12 個月 " + w.eps +
          " 元;× 自身過去本益比中位數 " + w.band[1] + " 倍 = <b>" + w.fair + "</b> 元,合理區間 " + w.low + " ~ " + w.high + "(" + w.band[0] + "~" + w.band[2] + " 倍)。</p>"
          : '<p class="fvhow">沒有足夠的分析師 EPS 預估。</p>') +
        (t ? '<p class="fvhow">分析師平均目標價 <b>' + t.mean + "</b>(最低 " + (t.lo == null ? "—" : t.lo) + "、最高 " + (t.hi == null ? "—" : t.hi) + "),相對現價 " + MR.sign(t.up, 1) + "%。</p>" : "") +
        (t && w && w.eps > 0 && Math.abs(t.mean / w.fair - 1) > 0.3 ? '<p class="fvhow">為什麼差這麼多:兩邊用的是同一組 EPS 預估,差在本益比。目標價等於給未來 12 個月 EPS <b>' +
          (t.mean / w.eps).toFixed(1) + " 倍</b>,這裡用的是這檔自己過去的本益比中位數 <b>" + w.band[1] + " 倍</b>。" +
          (t.mean > w.fair ? "分析師認為公司已經「變了」(例如打進 AI 供應鏈),值得比過去更高的評價;這個模型假設評價會回到過去水準。景氣循環股過去高獲利時本益比偏低,也會讓中位數偏低。"
            : "分析師給的評價低於這檔過去的水準,常見於獲利高峰的景氣循環股(預期之後會下滑)。") +
          "目標價的共識從 2026-10 才開始記錄,哪一邊比較準還無法回測。</p>" : "") +
        '<p class="fvhow">資料來源 Yahoo Finance 匯總的分析師共識,通常偏樂觀;這個前瞻估值從 2026-10 才開始記錄,尚未經過回測。</p></div>';
    }
    return fwdHtml + '<div class="fvbox"><h4>保守價位 · 依過去四季 EPS</h4>' +
      '<div class="fvgrid"><div><span>目前股價</span><b>' + px + "</b></div>" +
      "<div><span>模型合理價</span><b>" + e.fair + "</b></div>" +
      "<div><span>合理區間</span><b>" + e.low + " ~ " + e.high + "</b></div>" +
      '<div><span>潛在空間</span><b class="' + MR.dir(e.up) + '">' + MR.sign(e.up, 1) + "%</b></div>" +
      '<div><span>評價</span><b class="' + cls + '">' + e.status + "</b></div></div>" +
      '<div class="fvbar" aria-hidden="true"><i style="left:' + at(e.low) + ";width:calc(" + at(e.high) + " - " + at(e.low) + ')"></i>' +
      '<u style="left:' + at(e.fair) + '"></u><s style="left:' + at(px) + '"></s></div>' +
      '<p class="fvhow">' + how + "</p>" +
      (e.extreme ? '<p class="fvhow" style="color:var(--down)">⚠ 合理價與股價差距超過常理範圍,多半是景氣轉折(獲利剛開始暴增或衰退)、一次性損益或市場重新評價,這個固定公式不適用於這檔。</p>' : "") +
      '<p class="fvhow">公式固定、沒有人為調整;假設淨利率不變、評價回到自己的歷史中位數,實際上兩者都會變。回測顯示:2023–2026 被判「低估」的股票之後反而表現較差,這個合理價目前沒有預測力,只供了解估值位置。</p></div>';
  }

  // 公司概況:產業、主要業務、產品營收比重、概念股
  function profileHtml(p) {
    if (!p || !(p.ind || p.biz || p.mix)) return "";
    var mix = (p.mix || []).filter(function (x) { return x[1] > 0; });
    var shown = mix.slice(0, 6), rest = mix.slice(6).reduce(function (s, x) { return s + x[1]; }, 0);
    if (rest >= 0.5) shown.push(["其餘 " + (mix.length - 6) + " 項", Math.round(rest * 100) / 100]);
    var mx = Math.max.apply(null, shown.map(function (x) { return x[1]; }).concat([1]));
    var facts = [];
    if (p.ind) facts.push("<div><span>產業</span><b>" + esc(p.ind) + "</b></div>");
    if (p.capital != null) facts.push("<div><span>股本</span><b>" + esc(p.capital) + " 億</b></div>");
    if (p.listed) facts.push("<div><span>上市(櫃)</span><b>" + esc(p.listed.slice(0, 4)) + " 年</b></div>");
    if (p.founded) facts.push("<div><span>成立</span><b>" + esc(p.founded.slice(0, 4)) + " 年</b></div>");
    return '<div class="fvbox prof"><h4>公司概況</h4>' +
      (facts.length ? '<div class="fvgrid">' + facts.join("") + "</div>" : "") +
      (p.biz ? '<p class="fvhow"><b>主要業務</b> ' + esc(p.biz) + "</p>" : "") +
      (shown.length ? '<p class="fvhow" style="margin-bottom:4px"><b>產品營收比重</b>' + (p.mix_year ? "(" + esc(p.mix_year) + " 年)" : "") + "</p>" +
        '<div class="mixbars">' + shown.map(function (x) {
          return '<div class="mixrow"><span class="mixname">' + esc(x[0]) + '</span><span class="mixbar"><i style="width:' +
            (x[1] / mx * 100).toFixed(1) + '%"></i></span><span class="mixpct num">' + x[1].toFixed(1) + "%</span></div>";
        }).join("") + "</div>" : "") +
      (p.concepts && p.concepts.length ? '<p class="fvhow"><b>概念股分類</b> ' + p.concepts.map(function (c) {
        return '<span class="cpt">' + esc(c) + "</span>";
      }).join("") + "</p>" : "") +
      '<p class="fvhow" style="color:var(--faint)">來源:Yahoo 股市(產業、業務、概念股,Yahoo 頁面只列出部分分類)、MoneyDJ(營收比重,取自年報)。題材與比重只供了解公司在做什麼,不是選股依據。</p></div>';
  }

  function revHtml(doc) {
    var r = (doc.extra || {}).rev || [];
    if (r.length < 6) return "";
    var mx = Math.max.apply(null, r.map(function (x) { return x[1] || 0; })) || 1;
    var last = r[r.length - 1];
    return '<div class="mem-tools"><h4>月營收 · 近 ' + r.length + " 個月</h4></div>" +
      '<div class="revbars">' + r.map(function (x) {
        return '<i title="' + esc(x[0]) + " 營收 " + x[1] + " 億,年增 " + (x[2] == null ? "—" : x[2] + "%") + '" style="height:' + Math.max(2, (x[1] || 0) / mx * 100).toFixed(0) +
          "%;background:" + (x[2] > 0 ? "var(--up)" : x[2] < 0 ? "var(--down)" : "var(--muted)") + '"></i>';
      }).join("") + "</div>" +
      '<div class="kchart"><div class="cap"><span>' + esc(r[0][0]) + "</span><span>最新 " + esc(last[0]) + ":" + last[1] + " 億,年增 " + (last[2] == null ? "—" : MR.sign(last[2], 1) + "%") +
      "</span></div></div>";
  }

  // 季度毛利率:近 8 季,最新一季與去年同季比較
  function gmHtml(doc) {
    var h = (doc.extra || {}).gm || [];
    if (h.length < 2) return "";
    var v = h.map(function (x) { return x[1]; });
    var lo = Math.min.apply(null, v.concat([0])), hi = Math.max.apply(null, v), rg = hi - lo || 1;
    var last = h[h.length - 1], ly = null;
    h.forEach(function (x) { if (x[0] === (+last[0].slice(0, 4) - 1) + last[0].slice(4)) ly = x[1]; });
    var d = ly == null ? null : last[1] - ly;
    return '<div class="mem-tools"><h4>毛利率 · 近 ' + h.length + " 季</h4></div>" +
      '<div class="revbars gmbars">' + h.map(function (x) {
        return '<i title="' + esc(x[0]) + " 毛利率 " + x[1] + '%" style="height:' + Math.max(3, (x[1] - lo) / rg * 100).toFixed(0) + '%"><em>' + x[1] + "</em></i>";
      }).join("") + "</div>" +
      '<div class="kchart"><div class="cap"><span>' + esc(h[0][0]) + "</span><span>最新 " + esc(last[0]) + ":" + last[1] + "%" +
      (d == null ? "" : ",比去年同季 " + MR.sign(d, 1) + " 個百分點") + "</span><span>" + esc(last[0]) + "</span></div></div>" +
      '<p class="fvhow">回測顯示,營收創新高的股票裡,毛利率下降的組別之後表現沒有明顯比較差,這裡只供了解獲利品質。</p>';
  }

  function peHtml(doc) {
    var h = (doc.extra || {}).pe_hist || [], e = (doc.extra || {}).fv;
    if (h.length < 12 || !e || e.method !== "pe") return "";
    var v = h.map(function (x) { return x[1]; }), W = 600, H = 90;
    var lo = Math.min.apply(null, v.concat([e.band[0]])), hi = Math.max.apply(null, v.concat([e.band[2]])), rg = hi - lo || 1;
    var y = function (x) { return (H - 4 - (x - lo) / rg * (H - 8)).toFixed(1); };
    var pts = v.map(function (x, i) { return (i / (v.length - 1) * W).toFixed(1) + "," + y(x); }).join(" ");
    var band = '<rect x="0" y="' + y(e.band[2]) + '" width="' + W + '" height="' + (y(e.band[0]) - y(e.band[2])).toFixed(1) + '" fill="var(--accent)" opacity=".12"/>' +
      '<line x1="0" x2="' + W + '" y1="' + y(e.band[1]) + '" y2="' + y(e.band[1]) + '" stroke="var(--accent)" stroke-dasharray="4 3"/>';
    return '<div class="mem-tools"><h4>本益比歷史(每月) · 色帶為 25~75 百分位</h4></div><div class="kchart">' +
      '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" style="height:' + H + 'px">' + band +
      '<polyline points="' + pts + '" fill="none" stroke="var(--text)" stroke-width="1.5"/></svg>' +
      '<div class="cap"><span>' + esc(h[0][0]) + "</span><span>中位數 " + e.band[1] + " 倍 · 目前 " + (e.pe == null ? "—" : e.pe + " 倍") + "</span><span>" + esc(h[h.length - 1][0]) + "</span></div></div>";
  }

  // 評級說明:每一級歷史上的表現(起漲雷達 latest.json 帶研究結果)
  var starStatsP = null;
  function starStats() {
    if (!starStatsP) starStatsP = MR.json("data/radar/latest.json").then(function (r) {
      var s = (r.explosion || {}).stars || null;
      if (s) { s.regime = (r.explosion || {}).regime; s.landmine = (r.explosion || {}).landmine; }
      return s;
    }).catch(function () { return null; });
    return starStatsP;
  }
  function starNote(n, S) {
    var s = S && S.filter(function (x) { return x.stars === n; })[0];
    if (!s || !s.oos || s.oos.hit == null || !s.is || s.is.hit == null) return "";
    return '<p class="fvhow">歷史上同樣 ' + n + " 顆星的股票:之後 120 日內翻倍的比例 " + s.is.hit.toFixed(1) + "%(2019–22)/ " + s.oos.hit.toFixed(1) +
      "%(2023 後),60 日平均比一般股 " + MR.sign(s.is.x60, 1) + "% / " + MR.sign(s.oos.x60, 1) + "%,60 日內曾跌 25% 的有 " + s.is.crash.toFixed(0) + "% / " + s.oos.crash.toFixed(0) +
      "%。評級是統計上的機率,不是保證會漲,也不是個人化的投資建議;請分散、控制投入金額。</p>";
  }

  // ---- 個股健檢:逐項列出條件、是否符合、這一項在回測裡有沒有預測力,最後依規則給結論 ----
  // ok: 1 符合 / 0 中性 / -1 不符合或陷阱;ev: "回測" 有回測依據、"參考" 沒有預測力或尚未回測
  // 地雷條件(scripts/quality.py flags):回測(scripts/landmine_test.py)顯示前三項在兩段時期大跌機率都明顯較高,
  // 其餘三項沒有一致影響;平均報酬則都沒有一致影響,所以只當「風險」提示,不影響星等
  var MINE_STRONG = ["本業虧損", "累積虧損", "淨值跌破面額"];
  var MINE_TXT = { "本業虧損": function (v) { return "近 4 季營業利益合計 " + (v / 1e5).toFixed(1) + " 億"; },
    "獲利靠業外": function (v) { return "業外佔稅前淨利 " + v + "%"; }, "負債比偏高": function (v) { return "負債比 " + v + "%"; },
    "流動比率 < 100%": function (v) { return "流動比率 " + v + "%"; }, "淨值跌破面額": function (v) { return "每股淨值 " + v + " 元"; },
    "累積虧損": function (v) { return "保留盈餘 " + (v / 1e5).toFixed(1) + " 億"; } };
  var MINE_STATS = null;

  function checks(h) {
    var L = [];
    function add(name, ok, val, note, ev) { L.push({ name: name, ok: ok, val: val, note: note, ev: ev }); }
    function pc(v, d) { return v == null ? "—" : MR.sign(v, d == null ? 0 : d) + "%"; }
    add("營收動能", h.rev_ok ? 1 : 0, (h.rev_month ? h.rev_month.slice(5).replace(/^0/, "") + " 月年增 " : "年增 ") + pc(h.yoy) + (h.streak ? ",連續創新高 " + h.streak + " 個月" : ""),
      h.rev_ok ? "月營收創 12 個月新高且年增夠高" : "最新營收沒有創 12 個月新高(或年增不夠)", "回測");
    add("營收趨勢", h.accel == null ? 0 : h.accel <= -20 ? -1 : h.accel > 0 ? 1 : 0, "近 3 月年增 " + pc(h.yoy3) + "(比 3 個月前 " + (h.accel == null ? "—" : MR.sign(h.accel, 0) + " 個百分點") + ")",
      h.accel != null && h.accel <= -20 ? "陷阱:成長在減速,歷史上之後表現較差" : h.accel > 0 ? "成長在加速" : "持平", "回測");
    add("股價動能", h.ret60 == null ? 0 : h.ret60 >= 20 ? 1 : h.ret60 < 0 ? -1 : 0, "60 日 " + pc(h.ret60) + (h.above_ma60 === false ? ",在季線下" : ""),
      h.ret60 >= 20 ? "已經開始漲(動能是翻倍股最強的共同點)" : h.ret60 < 0 ? "股價還在跌" : "動能不足", "回測");
    add("題材(同產業)", h.peer60 == null ? 0 : h.peer60 >= 15 ? 1 : 0, (h.ind || "同產業") + " 60 日平均 " + pc(h.peer60),
      h.peer60 >= 15 ? "同產業一起走強" : "同產業沒有一起漲", "回測");
    add("外資", h.fo20 != null && h.fo20 <= -10 ? -1 : 0, "20 日買賣超佔成交 " + pc(h.fo20, 1),
      h.fo20 != null && h.fo20 <= -10 ? "陷阱:外資大賣,歷史上很少飆" : "沒有大賣(外資大買在回測裡也沒有比較好)", "回測");
    var risk = h.ret60 != null && h.ret60 >= 100 ? -1 : h.low_vol ? 0 : 0;
    add("位置與波動", risk, (h.hi250 != null && h.hi250 >= 0 ? "創 52 週新高(高於前高 " + pc(h.hi250) + ")" : "距 52 週高 " + pc(h.hi250)) + (h.low_vol ? ",低波動股" : ""),
      h.ret60 >= 100 ? "60 日已漲超過一倍,之後中途大跌的機率約 3–4 成" : h.low_vol ? "波動低,很難有爆發力" : "—", "回測");
    add("流動性", h.value20 == null ? 0 : h.value20 < 0.3 ? -1 : h.value20 < 1 ? 0 : 1, "20 日均成交 " + (h.value20 == null ? "—" : h.value20.toFixed(2) + " 億"),
      h.value20 < 0.3 ? "成交太少,買賣容易被價差吃掉、出不掉" : h.value20 < 1 ? "成交偏少,大額進出要小心" : "足夠", "回測");
    add("毛利率", 0, h.gm == null ? "—" : (h.gm_p || "") + " " + h.gm + "%" + (h.dgm == null ? "" : ",比去年同季 " + MR.sign(h.dgm, 1) + " 個百分點"),
      "了解獲利品質用;回測顯示毛利率升降對之後股價沒有預測力", "參考");
    add("估值", 0, h.fpe == null ? "無前瞻估值" : "前瞻本益比 " + h.fpe + " 倍" + (h.fpe_src === "自行推估" ? "(自行推估)" : "") + "(自身歷史中位 " + h.fpe_med + " 倍)" + (h.fwd_status ? "," + h.fwd_status : "") +
      (h.tgt_up == null ? "" : ",目標價空間 " + MR.sign(h.tgt_up, 0) + "%"), "分析師共識 2026-10 才開始記錄,尚未回測;歷史本益比估值回測沒有預測力", "參考");
    // 技術面(scripts/technical.py):順勢訊號歷史上偏好,抄底訊號(超賣、低檔黃金交叉)反而偏差
    var ta = h.ta;
    if (ta) {
      var EV = { "均線多頭排列": 1, "均線空頭排列": -1, "站上年線": 1, "跌破年線": -1, "KD 低檔黃金交叉": -1, "KD 高檔鈍化": 1, "RSI > 70": 1, "RSI < 30": -1,
        "MACD 柱狀翻正": 0, "MACD 在零軸上": 1, "突破布林上軌": 1, "布林通道收窄": -1, "價漲量增": 1, "價跌量增": -1, "向上跳空缺口": 1 };
      var pos = ta.on.filter(function (k) { return EV[k] > 0; }), neg = ta.on.filter(function (k) { return EV[k] < 0; });
      var v = ta.v || {};
      add("技術面", pos.length > neg.length ? 1 : neg.length > pos.length ? -1 : 0,
        "KD " + (v.K == null ? "—" : v.K.toFixed(0) + "/" + v.D.toFixed(0)) + " · RSI " + (v.RSI == null ? "—" : v.RSI.toFixed(0)) +
          (pos.length ? " · 偏多:" + pos.join("、") : "") + (neg.length ? " · 偏空:" + neg.join("、") : ""),
        "回測(2020–2026)顯示台股順勢訊號(均線多頭、RSI 過熱、KD 高檔鈍化、突破)之後較好;抄底訊號(RSI 超賣、KD 低檔黃金交叉)反而較差", "回測");
    }
    var mines = h.mines;
    if (mines) {
      var ks = Object.keys(mines), strong = ks.filter(function (k) { return MINE_STRONG.indexOf(k) >= 0; });
      var st = strong.map(function (k) { var s = MINE_STATS && MINE_STATS[k]; return s && s.is[0] != null ? k + " 的股票 60 日內曾跌 25% 的有 " + s.is[0] + "% / " + s.oos[0] + "%(沒有的 " + s.is[1] + "% / " + s.oos[1] + "%)" : ""; }).filter(Boolean);
      add("財務地雷(" + esc(h.mines_p || "") + ")", strong.length ? -1 : ks.length ? 0 : 1,
        ks.length ? ks.map(function (k) { return k + ":" + MINE_TXT[k](mines[k]); }).join(";") : "6 項都沒有",
        strong.length ? "大跌風險較高。4★ 以上裡," + (st.join(";") || "這些條件的大跌機率約高 1.5–2.5 倍") + "(2019–22 / 2023 後);平均報酬則沒有一致變差"
          : ks.length ? "這幾項在回測裡對之後的表現沒有一致影響" : "本業有賺、沒有累積虧損、負債與流動比率正常(財報狗式地雷條件)",
        strong.length || !ks.length ? "回測" : "參考");
    }
    if (h.punish || h.notice) {
      add("交易所處置 / 注意", h.punish ? -1 : 0, h.punish ? "處置中 " + (h.punish.period || "") : "列注意股 " + (h.notice.date || ""),
        h.punish ? "交易所處置:" + (h.punish.why || "") + "。處置期間改人工撮合、可能要預收款券,進出困難" : "交易所公告注意:" + (h.notice.why || "").slice(0, 60), "參考");
    }
    var rv = h.revision;
    add("分析師預估調整", rv && rv.eps1 != null ? (rv.eps1 > 1 ? 1 : rv.eps1 < -1 ? -1 : 0) : 0,
      rv ? "近 " + rv.days + " 天 明年 EPS 預估 " + (rv.eps1 == null ? "—" : MR.sign(rv.eps1, 1) + "%") + (rv.tgt == null ? "" : ",目標價 " + MR.sign(rv.tgt, 1) + "%") : "資料累積中",
      rv ? (rv.eps1 > 1 ? "分析師在上修" : rv.eps1 < -1 ? "分析師在下修" : "幾乎沒變") + "(Zacks 評級的核心訊號;我們的快照 2026-10 才開始存,半年後才能回測)" : "每天存一份分析師共識,累積 5 天以上才開始比較", "參考");
    return L;
  }

  function verdict(h, r) {
    var n = (r && r.stars) || 1;
    if (h && h.value20 != null && h.value20 < 0.3) return { cls: "no", t: "不適合:成交量太小", d: "20 日平均成交不到 0.3 億,回測也排除這類股票,進出成本與風險都高。" };
    if (h && h.punish && n >= 3) return { cls: "mid", t: "暫緩:交易所處置中", d: "評級 " + n + "★,但處置期間(" + (h.punish.period || "") + ")改人工撮合、可能要預收款券,進出受限;處置結束後再看。" };
    if (n >= 5) return { cls: "yes", t: "符合條件最多:可列入分散組合的候選", d: "營收、動能、題材都有,沒有營收減速或外資大賣的陷阱。這是統計上機率較高,不代表這一檔一定會漲。" };
    if (n === 4) return { cls: "yes", t: "可列入分散組合的候選", d: r.traps && r.traps.length ? "條件齊全但有陷阱(" + r.traps.join("、") + "),已扣一顆星。" : "營收成立,動能與題材其中一項還沒到。" };
    if (n === 3) return { cls: "mid", t: "觀察:條件還沒到齊", d: r.tier === "C" ? "營收已經轉強,但股價和同產業都還沒動;最早期、空間最大,但多數不會飆。" : r.tier === "D" ? "股價與同產業都在漲,但營收還沒跟上;同類股很多,多數只是跟漲。" : "有陷阱,已扣一顆星。" };
    if (n === 2) return { cls: "no", t: "暫不符合:有陷阱", d: "營收雖然轉強,但有陷阱(" + ((r.traps || []).join("、") || "—") + "),歷史上之後表現接近一般股。" };
    return { cls: "no", t: "目前不符合起漲條件", d: "不在起漲雷達任何名單。歷史上這類股票之後平均比一般股略差;不代表公司不好,只是現在沒有起漲的訊號。" };
  }

  // 大盤空頭時評級效果明顯變弱(scripts/accuracy_study.py [3])
  function regimeNote(h, r, S) {
    if (!h || h.bull !== false || !r || (r.stars || 1) < 4) return "";
    var g = S && S.regime && S.regime["5★ · 大盤空頭"], s = g && g.is;
    return '<div class="vd warn"><b>⚠ 目前大盤在 60 日均線下(空頭)</b><span>' +
      (s && s.hit != null ? "歷史上空頭時的 5★,60 日中位數 " + MR.sign(s.med60, 1) + "%、60 日內曾跌 25% 的有 " + s.crash.toFixed(0) + "%(多頭時約 14–23%)," : "") +
      "評級效果明顯變弱,宜降低投入或分批。</span></div>";
  }

  MR.verdict = function (h, r) { return verdict(h, r); };

  // 同業百分位(scripts/radar.py peer_rank):這檔在同產業裡贏過多少比例的公司
  function peerHtml(h) {
    var p = h && h.peer;
    if (!p) return "";
    var items = [["yoy3", "營收成長(近 3 月年增)"], ["ret60", "股價動能(60 日)"], ["gm", "毛利率"], ["dgm", "毛利率改善"], ["fpe", "前瞻本益比便宜程度"]]
      .filter(function (k) { return p[k[0]] != null; });
    if (!items.length) return "";
    return '<div class="peer"><h5>同業比較 · ' + esc(p.ind) + " " + p.n + ' 家<span class="evb">僅供參考</span></h5>' + items.map(function (k) {
      var v = p[k[0]];
      return '<div class="pr"><span class="pr-n">' + esc(k[1]) + '</span><span class="pr-b"><i style="width:' + v + '%"></i></span><span class="pr-v">贏過 ' + v + "%</span></div>";
    }).join("") + '<p class="fvhow">和同一證交所產業別的公司比(本益比只比有分析師預估的 ' + (p.m_fpe || 0) + " 家)。同業排名本身沒有經過回測,評級與結論不使用它。</p></div>";
  }

  function mineNote(h, r) {
    var m = h && h.mines;
    if (!m || !r || (r.stars || 1) < 3) return "";
    var strong = Object.keys(m).filter(function (k) { return MINE_STRONG.indexOf(k) >= 0; });
    if (!strong.length) return "";
    return '<div class="vd warn"><b>⚠ 財務地雷:' + esc(strong.join("、")) + "</b><span>回測顯示這類股票中途大跌的機率約高 1.5–2.5 倍;評級看的是報酬,沒有扣分,但投入金額宜更少。</span></div>";
  }

  function healthHtml(h, r, S) {
    if (S && S.landmine) MINE_STATS = S.landmine;
    var v = verdict(h, r), rows = h ? checks(h) : [];
    var ic = { "1": '<b class="ck ok">✓</b>', "0": '<b class="ck mid">–</b>', "-1": '<b class="ck no">✕</b>' };
    return '<div class="fvbox health"><h4>個股健檢</h4><div class="rt">' + MR.ratingLine(r) + "</div>" +
      '<div class="vd ' + v.cls + '"><b>' + esc(v.t) + "</b><span>" + esc(v.d) + "</span></div>" + regimeNote(h, r, S) + mineNote(h, r) +
      (rows.length ? '<table class="hc"><tbody>' + rows.map(function (x) {
        return "<tr><td>" + ic[String(x.ok)] + "</td><th>" + esc(x.name) + '</th><td class="hv">' + esc(x.val) + '</td><td class="hn">' + esc(x.note) +
          '<span class="evb ' + (x.ev === "回測" ? "bt" : "") + '">' + (x.ev === "回測" ? "有回測依據" : "僅供參考") + "</span></td></tr>";
      }).join("") + "</tbody></table>" : "") +
      peerHtml(h) + starNote((r && r.stars) || 1, S) +
      '<p class="fvhow">要投入的話:依回測,從名單只買 1 檔,約 18% 的機率 60 日內虧超過 15%;分散買 10 檔降到約 5%。單檔建議不超過可投入金額的 1/10,並且只用虧得起的錢。這是依固定規則整理的統計結果,不是針對你個人的投資建議。</p></div>';
  }

  function stockHtml(doc, stats, prof) {
    var s = doc.summary, sigs = (stats && stats.signals) || {}, names = {}, grades = {};
    Object.keys(sigs).forEach(function (k) { names[k] = sigs[k].name; grades[k] = sigs[k].horizons["10"].grade; });
    var off = s.high250 ? (s.close / s.high250 - 1) * 100 : null;
    var recent = (doc.signals || []).slice(-8).reverse();
    return '<div class="sh-head"><div><h3 id="stk-title"><span class="num">' + esc(doc.code) + "</span> " + esc(doc.name) + " " + MR.watchBtn(doc.code) + "</h3>" +
      '<div class="stk-head" id="stk-px"><span class="px">' + esc(s.close) + "</span>" + MR.pct(s.chg) +
      '<span class="flat" style="font-size:12px">' + esc(doc.date) + " 收盤</span></div>" +
      (doc.themes.length ? '<div class="chips">' + doc.themes.map(function (t) {
        return '<a class="th-chip" href="sectors.html#' + esc(t.id) + '">' + esc(t.name) + "</a>";
      }).join("") + "</div>" : "") +
      '</div><button type="button" class="x" data-close aria-label="關閉">×</button></div>' +
      '<div class="sh-body">' + '<div id="health">' + healthHtml(doc.health, doc.rating, null) + "</div>" +
      profileHtml(prof && prof[doc.code]) + fvHtml(doc) +
      '<div class="kgrid">' +
      "<div><span>5 日漲跌</span><b>" + MR.pct(s.ret5) + "</b></div>" +
      "<div><span>20 日漲跌</span><b>" + MR.pct(s.ret20) + "</b></div>" +
      "<div><span>距 52 週高點</span><b>" + MR.pct(off) + "</b></div>" +
      "<div><span>5 日法人</span><b>" + MR.yi(s.net5) + "</b></div>" +
      "<div><span>20 日法人</span><b>" + MR.yi(s.net20) + "</b></div>" +
      "<div><span>20 日均成交</span><b>" + (s.avg_value20 == null ? "—" : s.avg_value20.toFixed(1) + " 億") + "</b></div>" +
      "<div><span>外資連買</span><b>" + s.foreign_streak + " 天</b></div>" +
      "<div><span>投信連買</span><b>" + s.trust_streak + " 天</b></div>" +
      "<div><span>今日法人</span><b>" + MR.yi(lastNet(doc)) + "</b></div>" +
      "</div>" + kchart(doc, names, grades) + revHtml(doc) + gmHtml(doc) + peHtml(doc) +
      '<div class="mem-tools"><h4>近期訊號 · 歷史 10 日表現</h4></div>' +
      (recent.length ? '<ul class="siglist">' + recent.map(function (m) {
        var st = sigs[m[1]], h = st && st.horizons["10"];
        var stat = h && h.all.n ? "勝過一般股 " + h.all.win + "% · 平均相對 " + MR.sign(h.all.avg_rel, 2) + "%" : "";
        return '<li><span class="d">' + MR.md(m[0]) + "</span><span>" + esc(st ? st.name : m[1]) + (h ? MR.gradeTag(h.grade) : "") +
          '</span><span class="w">' + stat + "</span></li>";
      }).join("") + "</ul>" : '<p class="flat" style="font-size:14px">近 ' + doc.rows.length + " 個交易日沒有觸發訊號。</p>") +
      '<p class="foot">歷史表現是同一訊號在所有個股上的統計,不是這檔股票的預測;' +
      '<a href="signals.html">看回測方法與完整數據</a>。只呈現事實,不構成投資建議。</p></div>';
  }

  function lastNet(doc) {
    var r = doc.rows[doc.rows.length - 1];
    return r ? (r[6] || 0) + (r[7] || 0) + (r[8] || 0) : null;
  }

  MR.openStock = function (code) {
    var d = ensureDialog();
    d.innerHTML = '<div class="sh-head"><div><h3 id="stk-title">' + esc(code) + '</h3></div><button type="button" class="x" data-close aria-label="關閉">×</button></div><div class="sh-body"><p class="flat">載入中…</p></div>';
    if (!d.open) d.showModal();
    Promise.all([MR.json("data/stocks/" + encodeURIComponent(code) + ".json"), MR.stats(), MR.profile()])
      .then(function (res) {
        d.innerHTML = stockHtml(res[0], res[1], res[2]);
        starStats().then(function (S) { var n = d.querySelector("#health"); if (n) n.innerHTML = healthHtml(res[0].health, res[0].rating, S); });
        // 盤中或今日收盤後:用即時報價取代排程資料的收盤價(live.js 有載入且已設定 Worker 才會有)
        if (MR.intradayOne) MR.intradayOne(code, res[0].date).then(function (lv) {
          var el = d.querySelector("#stk-px");
          if (!lv || !el || !d.open) return;
          el.innerHTML = '<span class="px">' + lv.q[1] + "</span>" + MR.pct(lv.q[2]) + '<span class="flat" style="font-size:12px">' +
            (lv.open ? "盤中即時 " + esc(String(lv.q[4]).slice(0, 5)) : esc(lv.date) + " 收盤") + "</span>";
        });
      })
      .catch(function () { brief(d, code); });
  };

  // 沒有詳細面板的股票:用查詢索引顯示精簡資料
  function brief(d, code) {
    Promise.all([MR.index(), MR.profile(), starStats()]).then(function (res) {
      var I = res[0], x = I && I.s[code], body = d.querySelector(".sh-body");
      if (!x) { body.innerHTML = '<p class="flat">查無這檔股票(只收錄上市櫃普通股)。</p>'; return; }
      var r = { stars: x[1], tier: x[2], traps: x[11] }, p = res[1] && res[1][code];
      d.querySelector(".sh-head").innerHTML = '<div><h3 id="stk-title"><span class="num">' + esc(code) + "</span> " + esc(x[0]) + " " + MR.watchBtn(code) + "</h3>" +
        '<div class="stk-head" id="stk-px"><span class="px">' + esc(x[3]) + "</span>" + MR.pct(x[4]) + '<span class="flat" style="font-size:12px">' + esc(I.date) + " 收盤</span></div></div>" +
        '<button type="button" class="x" data-close aria-label="關閉">×</button>';
      body.innerHTML = healthHtml(x[12], r, res[2]) +
        profileHtml(p) +
        '<div class="kgrid"><div><span>60 日漲跌</span><b>' + MR.pct(x[5]) + "</b></div><div><span>產業</span><b>" + esc(x[6] || "—") + "</b></div>" +
        "<div><span>最新營收年增" + (x[9] ? "(" + esc(x[9].slice(5).replace(/^0/, "")) + " 月)" : "") + "</span><b>" + MR.pct(x[7]) + "</b></div>" +
        "<div><span>近 3 月營收年增</span><b>" + MR.pct(x[8]) + "</b></div></div>" +
        '<p class="foot">這檔不在起漲雷達、觀察名單或板塊成分股裡,所以沒有 K 線、法人與估值的詳細資料。只呈現事實,不構成投資建議。</p>';
      if (MR.intradayOne) MR.intradayOne(code, I.date).then(function (lv) {
        var el = d.querySelector("#stk-px");
        if (!lv || !el || !d.open) return;
        el.innerHTML = '<span class="px">' + lv.q[1] + "</span>" + MR.pct(lv.q[2]) + '<span class="flat" style="font-size:12px">' +
          (lv.open ? "盤中即時 " + esc(String(lv.q[4]).slice(0, 5)) : esc(lv.date) + " 收盤") + "</span>";
      });
    });
  }

  // ---- 個股查詢:導覽列上的搜尋框,輸入代號或名稱 ----
  function setupSearch() {
    var inner = document.querySelector(".bar-in");
    if (!inner || document.getElementById("stk-q")) return;
    var box = document.createElement("div");
    box.className = "srch";
    box.innerHTML = '<input id="stk-q" type="search" placeholder="查個股:代號或名稱" autocomplete="off" aria-label="查詢個股">' +
      '<ul id="stk-sug" role="listbox" hidden></ul>';
    inner.insertBefore(box, inner.querySelector(".nav"));
    var q = box.querySelector("input"), ul = box.querySelector("ul"), items = [], sel = -1;
    function render() {
      ul.innerHTML = items.map(function (it, k) {
        return '<li role="option" data-code="' + esc(it[0]) + '"' + (k === sel ? ' aria-selected="true"' : "") + '><b class="num">' + esc(it[0]) + "</b> " + esc(it[1][0]) +
          '<span class="sg-r">' + MR.stars(it[1][1]) + "</span></li>";
      }).join("");
      ul.hidden = !items.length;
    }
    q.addEventListener("input", function () {
      var v = q.value.trim().toLowerCase();
      if (!v) { items = []; render(); return; }
      MR.index().then(function (I) {
        if (!I) return;
        var exact = [], pre = [], has = [];
        Object.keys(I.s).forEach(function (c) {
          var n = I.s[c][0].toLowerCase();
          if (c === v || n === v) exact.push([c, I.s[c]]);
          else if (c.indexOf(v) === 0 || n.indexOf(v) === 0) pre.push([c, I.s[c]]);
          else if (n.indexOf(v) >= 0) has.push([c, I.s[c]]);
        });
        items = exact.concat(pre, has).slice(0, 8);
        sel = items.length ? 0 : -1;
        render();
      });
    });
    function pick(code) {
      q.value = ""; items = []; render(); q.blur();
      MR.openStock(code);
    }
    q.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!items.length) return;
        e.preventDefault();
        sel = (sel + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
        render();
      } else if (e.key === "Enter" && sel >= 0 && items[sel]) {
        e.preventDefault(); pick(items[sel][0]);
      } else if (e.key === "Escape") { items = []; render(); }
    });
    ul.addEventListener("mousedown", function (e) {
      var li = e.target.closest("li[data-code]");
      if (li) { e.preventDefault(); pick(li.getAttribute("data-code")); }
    });
    q.addEventListener("blur", function () { setTimeout(function () { items = []; render(); }, 150); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setupSearch); else setupSearch();

  // ---- 表格點表頭排序(通用):排畫面上的列;第一次大到小,再點一次小到大。數字依大小、文字依筆畫,空值排最後 ----
  // 起漲雷達的排行表(.rank)只顯示前幾十筆,改由頁面自己對完整資料排序,這裡略過;多列表頭(有合併欄)的表也略過
  function cellVal(td) {
    var s = (td ? td.textContent : "").replace(/[−–]/g, "-").replace(/,/g, "").trim();
    if (!s || s === "—" || s === "-" || /累積中|樣本不足/.test(s)) return null;
    var m = s.match(/[-+]?\d+(\.\d+)?/);
    return m && /^[-+]?[\d.]/.test(s) ? parseFloat(m[0]) : s;
  }
  function sortable(table) {
    var th = table.tHead;
    return th && th.rows.length === 1 && !table.classList.contains("rank") && table.tBodies[0] && table.tBodies[0].rows.length > 1;
  }
  document.addEventListener("click", function (e) {
    var th = e.target.closest("thead th");
    if (!th || e.target.closest("button,a,input")) return;
    var table = th.closest("table");
    if (!sortable(table)) return;
    var col = Array.prototype.indexOf.call(th.parentNode.children, th);
    var dir = th.getAttribute("aria-sort") === "descending" ? 1 : -1;
    Array.prototype.forEach.call(th.parentNode.children, function (x) { x.removeAttribute("aria-sort"); });
    th.setAttribute("aria-sort", dir < 0 ? "descending" : "ascending");
    var body = table.tBodies[0], rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (ra, rb) {
      var a = cellVal(ra.cells[col]), b = cellVal(rb.cells[col]);
      if (a == null) return b == null ? 0 : 1;
      if (b == null) return -1;
      if (typeof a === "number" && typeof b === "number") return (a - b) * dir;
      return String(a).localeCompare(String(b), "zh-Hant") * dir;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  });
  // 可以排序的表頭加上樣式提示
  new MutationObserver(function () {
    Array.prototype.forEach.call(document.querySelectorAll("table:not(.srt-ok)"), function (tb) {
      if (!sortable(tb)) return;
      tb.classList.add("srt-ok");
      Array.prototype.forEach.call(tb.tHead.rows[0].cells, function (c) { if (c.textContent.trim()) { c.classList.add("srt"); c.title = c.title || "點一下排序"; } });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  // ---- 啟動畫面:每個瀏覽器分頁第一次開啟時顯示;頁面資料畫好(骨架消失)就淡出,最少 0.7 秒、最多 3 秒 ----
  (function splash() {
    var el = document.getElementById("splash");
    if (!el) return;
    if (document.documentElement.classList.contains("nosplash")) { el.remove(); return; }
    var t0 = Date.now(), gone = false;
    function hide() {
      if (gone) return;
      gone = true;
      setTimeout(function () {
        el.classList.add("done");
        try { sessionStorage.setItem("mr.splash", "1"); } catch (e) {}
        setTimeout(function () { el.remove(); }, 600);
      }, Math.max(0, 700 - (Date.now() - t0)));
    }
    function ready() { var app = document.getElementById("app"); return !app || !app.querySelector(".skel"); }
    var mo = new MutationObserver(function () { if (ready()) { mo.disconnect(); hide(); } });
    function start() {
      var app = document.getElementById("app");
      if (ready()) return hide();
      mo.observe(app, { childList: true });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
    setTimeout(hide, 3000);
    el.addEventListener("click", hide);
  })();

  // ---- 資料狀態(scripts/status.py 每次排程後檢查各來源是否按時更新),顯示在每頁底部 ----
  function statusLine() {
    var f = document.querySelector("footer");
    if (!f) return;
    MR.json("data/status.json").then(function (s) {
      var bad = (s.items || []).filter(function (x) { return !x.ok; });
      var when = esc(s.checked_at.slice(5, 16).replace("T", " "));
      var el = document.createElement("div");
      el.className = "dstat" + (bad.length ? " bad" : "");
      el.innerHTML = bad.length
        ? "<details><summary>⚠ 資料狀態:" + bad.length + " 項延遲(" + esc(bad.map(function (x) { return x.name; }).join("、")) + ")· 檢查 " + when + "</summary><ul>" +
          (s.items || []).map(function (x) { return "<li>" + (x.ok ? "✓ " : "⚠ ") + esc(x.name) + ":" + esc(x.last || "—") + (x.note ? "(" + esc(x.note) + ")" : "") + "</li>"; }).join("") + "</ul></details>"
        : '<details><summary>✓ 資料狀態:全部按時更新 · 檢查 ' + when + "</summary><ul>" +
          (s.items || []).map(function (x) { return "<li>" + esc(x.name) + ":" + esc(x.last || "—") + "</li>"; }).join("") + "</ul></details>";
      f.appendChild(el);
    }).catch(function () {});
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", statusLine); else statusLine();

  // 頂端導覽列的高度(手機會換行變高),給表格決定最大高度,讓整個表格框放得進導覽列下方
  function barHeight() {
    var b = document.querySelector(".bar");
    if (b) document.documentElement.style.setProperty("--bar-h", b.offsetHeight + "px");
  }
  window.addEventListener("resize", barHeight);
  document.addEventListener("DOMContentLoaded", barHeight);

  // 任何帶 data-stock 的元素點了就開個股面板
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-stock]");
    if (b) { e.preventDefault(); MR.openStock(b.getAttribute("data-stock")); }
  });
})();
