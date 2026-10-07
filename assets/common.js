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

  function stockHtml(doc, stats) {
    var s = doc.summary, sigs = (stats && stats.signals) || {}, names = {}, grades = {};
    Object.keys(sigs).forEach(function (k) { names[k] = sigs[k].name; grades[k] = sigs[k].horizons["10"].grade; });
    var off = s.high250 ? (s.close / s.high250 - 1) * 100 : null;
    var recent = (doc.signals || []).slice(-8).reverse();
    return '<div class="sh-head"><div><h3 id="stk-title"><span class="num">' + esc(doc.code) + "</span> " + esc(doc.name) + "</h3>" +
      '<div class="stk-head"><span class="px">' + esc(s.close) + "</span>" + MR.pct(s.chg) +
      '<span class="flat" style="font-size:12px">' + esc(doc.date) + " 收盤</span></div>" +
      (doc.themes.length ? '<div class="chips">' + doc.themes.map(function (t) {
        return '<a class="th-chip" href="sectors.html#' + esc(t.id) + '">' + esc(t.name) + "</a>";
      }).join("") + "</div>" : "") +
      '</div><button type="button" class="x" data-close aria-label="關閉">×</button></div>' +
      '<div class="sh-body">' +
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
      "</div>" + kchart(doc, names, grades) +
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
    Promise.all([MR.json("data/stocks/" + encodeURIComponent(code) + ".json"), MR.stats()])
      .then(function (res) { d.innerHTML = stockHtml(res[0], res[1]); })
      .catch(function () {
        d.querySelector(".sh-body").innerHTML = '<p class="flat">這檔股票目前沒有詳細資料(只收錄板塊成分股與近期觸發訊號的個股)。</p>';
      });
  };

  // 任何帶 data-stock 的元素點了就開個股面板
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-stock]");
    if (b) { e.preventDefault(); MR.openStock(b.getAttribute("data-stock")); }
  });
})();
