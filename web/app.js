/* The page's charts and the walk-through, drawn from data.json and nothing else.
 *
 * data.json is written by `mend site` from the same result files that `mend report` writes
 * the README's tables from, so the page and the repository cannot disagree.
 *
 * No framework and no charting library: every chart is SVG built with the DOM API, so the
 * content security policy can forbid inline scripts and styles outright. Colours live in
 * style.css and never here, which is what lets one palette follow the page into dark mode.
 *
 * Text from data only ever reaches the page through textContent. Nothing here writes HTML
 * from data.
 *
 * This file computes nothing the pipeline could have computed.
 */
"use strict";

(function () {
  var NS = "http://www.w3.org/2000/svg";
  var WIDTH = 880;

  /* Small DOM helpers ---------------------------------------------------------- */

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    if (attrs) { for (var key in attrs) { node.setAttribute(key, attrs[key]); } }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function svg(tag, attrs, text) {
    var node = document.createElementNS(NS, tag);
    if (attrs) { for (var key in attrs) { node.setAttribute(key, String(attrs[key])); } }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function byId(id) { return document.getElementById(id); }

  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } return node; }

  function isNumber(value) { return typeof value === "number" && isFinite(value); }

  /* Formatting ----------------------------------------------------------------- */

  function pct(value, digits) { return isNumber(value) ? (value * 100).toFixed(digits === undefined ? 1 : digits) + "%" : "n/a"; }

  function usd(value, digits) { return isNumber(value) ? "US$" + value.toFixed(digits === undefined ? 2 : digits) : "n/a"; }

  function ari(value) { return isNumber(value) ? value.toFixed(3) : "n/a"; }

  function range(v, format) { return format(v.low) + " to " + format(v.high); }

  /* Scales and axes ------------------------------------------------------------ */

  function linear(domain, outRange) {
    var f = function (v) { return outRange[0] + (v - domain[0]) / (domain[1] - domain[0]) * (outRange[1] - outRange[0]); };
    f.domain = domain;
    return f;
  }

  function ticks(lo, hi, wanted) {
    var span = hi - lo;
    var step = Math.pow(10, Math.floor(Math.log(span / wanted) / Math.LN10));
    var err = span / wanted / step;
    if (err >= 7.5) { step *= 10; } else if (err >= 3.5) { step *= 5; } else if (err >= 1.5) { step *= 2; }
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) { out.push(Math.round(v * 1e9) / 1e9); }
    return out;
  }

  /* No <title> child: the chart's accessible name is aria-label on role="img", and the readout
     under the chart tells the reader about the mark they are on. */
  function frame(height, title) {
    return svg("svg", { viewBox: "0 0 " + WIDTH + " " + height, role: "img", "aria-label": title, preserveAspectRatio: "xMidYMid meet" });
  }

  function legend(target, items) {
    var node = clear(byId(target));
    items.forEach(function (item) {
      var entry = el("span", { "class": "legend-item" });
      entry.appendChild(el("span", { "class": "swatch " + item[0], "aria-hidden": "true" }));
      entry.appendChild(document.createTextNode(item[1]));
      node.appendChild(entry);
    });
  }

  function hover(mark, readout, text) {
    var show = function () { byId(readout).textContent = text; };
    mark.setAttribute("tabindex", "0");
    mark.setAttribute("aria-label", text);
    mark.addEventListener("mouseenter", show);
    mark.addEventListener("focus", show);
    mark.addEventListener("click", show);
  }

  /* Horizontal bars, each with its interval as a whisker and its value beside the whisker.
     rows: { label, value: {est, low, high, n}, cls, note } */
  function bars(target, readout, rows, opts) {
    var rowH = 40, left = opts.left || 250, right = WIDTH - 70, top = 16;
    var height = top + rows.length * rowH + 30;
    var hi = opts.max !== undefined ? opts.max : Math.max.apply(null, rows.map(function (r) { return r.value.high; })) * 1.08;
    var lo = opts.min !== undefined ? opts.min : 0;
    var x = linear([lo, hi], [left, right]);
    var root = frame(height, opts.title);
    ticks(lo, hi, 5).forEach(function (v) {
      root.appendChild(svg("line", { x1: x(v), x2: x(v), y1: top - 6, y2: height - 26, "class": "gridline" }));
      root.appendChild(svg("text", { x: x(v), y: height - 8, "text-anchor": "middle", "class": "tick" }, (opts.tick || opts.format)(v)));
    });
    if (opts.baseline !== undefined) {
      root.appendChild(svg("line", { x1: x(opts.baseline), x2: x(opts.baseline), y1: top - 6, y2: height - 26, "class": "nominal" }));
      root.appendChild(svg("text", { x: x(opts.baseline) + 6, y: top + 2, "class": "zero-label halo" }, opts.baselineLabel));
    }
    rows.forEach(function (r, i) {
      var y = top + i * rowH;
      root.appendChild(svg("text", { x: left - 12, y: y + 19, "text-anchor": "end", "class": "row-label" }, r.label));
      var v = r.value;
      var bar = svg("rect", { x: x(lo), y: y + 8, width: Math.max(1, x(v.est) - x(lo)), height: 16, rx: 3, "class": "bar " + (r.cls || "seq1") });
      root.appendChild(bar);
      root.appendChild(svg("line", { x1: x(v.low), x2: x(v.high), y1: y + 16, y2: y + 16, "class": "whisker" }));
      root.appendChild(svg("line", { x1: x(v.low), x2: x(v.low), y1: y + 11, y2: y + 21, "class": "whisker" }));
      root.appendChild(svg("line", { x1: x(v.high), x2: x(v.high), y1: y + 11, y2: y + 21, "class": "whisker" }));
      root.appendChild(svg("text", { x: x(v.high) + 8, y: y + 20, "class": "bar-value" }, opts.format(v.est)));
      var catcher = svg("rect", { x: left, y: y + 2, width: right - left, height: rowH - 6, "class": "hit" });
      root.appendChild(catcher);
      var said = r.label + ": " + opts.format(v.est) + " (" + (opts.spread ? "spread across splits " : "95% interval ") + range(v, opts.format) + (v.n ? ", n = " + v.n : "") + ")" + (r.note ? ". " + r.note : "");
      hover(catcher, readout, said);
    });
    clear(byId(target)).appendChild(root);
  }

  /* Pairs of bars per group (two series), each with a whisker. */
  function pairedBars(target, readout, groups, series, opts) {
    var barH = 14, gap = 6, groupH = series.length * (barH + gap) + 18, left = opts.left || 250, right = WIDTH - 70, top = 12;
    var height = top + groups.length * groupH + 26;
    var x = linear([0, opts.max], [left, right]);
    var root = frame(height, opts.title);
    ticks(0, opts.max, 5).forEach(function (v) {
      root.appendChild(svg("line", { x1: x(v), x2: x(v), y1: top - 6, y2: height - 24, "class": "gridline" }));
      root.appendChild(svg("text", { x: x(v), y: height - 6, "text-anchor": "middle", "class": "tick" }, opts.format(v)));
    });
    groups.forEach(function (g, gi) {
      var y0 = top + gi * groupH;
      root.appendChild(svg("text", { x: left - 12, y: y0 + series.length * (barH + gap) / 2 + 4, "text-anchor": "end", "class": "row-label" }, g.label));
      series.forEach(function (s, si) {
        var v = g[s.key];
        var y = y0 + si * (barH + gap);
        root.appendChild(svg("rect", { x: left, y: y, width: Math.max(1, x(v.est) - left), height: barH, rx: 3, "class": "bar " + s.cls }));
        root.appendChild(svg("line", { x1: x(v.low), x2: x(v.high), y1: y + barH / 2, y2: y + barH / 2, "class": "whisker" }));
        root.appendChild(svg("text", { x: x(v.high) + 8, y: y + barH - 3, "class": "bar-value" }, opts.format(v.est)));
        var catcher = svg("rect", { x: left, y: y - 2, width: right - left, height: barH + 4, "class": "hit" });
        root.appendChild(catcher);
        hover(catcher, readout, g.label + ", " + s.label + ": " + opts.format(v.est) + " (95% interval " + range(v, opts.format) + ", n = " + v.n + ")");
      });
    });
    clear(byId(target)).appendChild(root);
  }

  /* Tables ------------------------------------------------------------------------- */

  function cell(row, text, cls) {
    var td = el("td", cls ? { "class": cls } : null);
    if (text instanceof Node) { td.appendChild(text); } else { td.textContent = text; }
    row.appendChild(td);
    return td;
  }

  function withInterval(main, interval) {
    var span = el("span");
    span.appendChild(document.createTextNode(main + " "));
    span.appendChild(el("span", { "class": "interval" }, interval));
    return span;
  }

  function link(href, text) { return el("a", { href: href }, text); }

  function resultRows(res) {
    var body = clear(byId("results-rows"));
    var add = function (label, r, strong) {
      var tr = el("tr", strong ? { "class": "reference" } : null);
      cell(tr, label);
      cell(tr, String(r.n), "num");
      cell(tr, withInterval(pct(r.hit.est), range(r.hit, pct)), "num");
      cell(tr, r.wrong ? withInterval(pct(r.wrong.est), range(r.wrong, pct)) : "", "num");
      cell(tr, withInterval(usd(r.cost_attempted.est), range(r.cost_attempted, usd)), "num");
      body.appendChild(tr);
    };
    res.tiers.forEach(function (t) { add(t.tier, t, false); });
    add("All " + res.all.n, { n: res.all.n, hit: res.all.hit, wrong: res.all.wrong, cost_attempted: res.all.cost_attempted }, true);
  }

  function caseRows(wrong) {
    var body = clear(byId("cases-rows"));
    wrong.cases.forEach(function (c) {
      var tr = el("tr");
      cell(tr, el("code", null, c.task));
      cell(tr, c.cause);
      cell(tr, c.why);
      body.appendChild(tr);
    });
  }

  function liveRows(live) {
    var body = clear(byId("live-rows"));
    live.runs.forEach(function (r) {
      var tr = el("tr");
      cell(tr, link(r.run, r.date));
      cell(tr, link(r.pull_request, r.repo));
      cell(tr, String(r.tests), "num");
      cell(tr, String(r.failures), "num");
      cell(tr, String(r.tickets), "num");
      cell(tr, r.outcome + (r.posted ? ", posted" : ""));
      cell(tr, usd(r.cost), "num");
      body.appendChild(tr);
    });
  }

  /* The walk-through ------------------------------------------------------------------- */

  function code(text, diff) {
    var pre = el("pre", { "class": "code" + (diff ? " diff" : "") });
    String(text).split("\n").forEach(function (line, i) {
      var cls = "";
      if (diff) {
        if (line.indexOf("+") === 0 && line.indexOf("+++") !== 0) { cls = "add"; }
        else if (line.indexOf("-") === 0 && line.indexOf("---") !== 0) { cls = "del"; }
      }
      if (i) { pre.appendChild(document.createTextNode("\n")); }
      pre.appendChild(el("span", cls ? { "class": cls } : null, line));
    });
    return pre;
  }

  function para(text) { return el("p", null, text); }

  function list(items, cls) {
    var ul = el("ul", { "class": cls || "plain" });
    items.forEach(function (item) { ul.appendChild(item instanceof Node ? (function () { var li = el("li"); li.appendChild(item); return li; })() : el("li", null, item)); });
    return ul;
  }

  function ticketBars(tickets) {
    var max = Math.max.apply(null, tickets.map(function (t) { return t.size; }));
    var wrap = el("div", { "class": "tickets" });
    tickets.forEach(function (t, i) {
      var row = el("div", { "class": "ticket" + (i === 0 ? " first" : "") });
      row.appendChild(el("span", { "class": "ticket-name" }, t.title));
      var track = el("span", { "class": "ticket-track" });
      for (var k = 0; k < max; k++) { track.appendChild(el("span", { "class": "pip" + (k < t.size ? " on" : "") })); }
      row.appendChild(track);
      row.appendChild(el("span", { "class": "ticket-size" }, t.size + (t.size === 1 ? " failure" : " failures")));
      wrap.appendChild(row);
    });
    return wrap;
  }

  function follow(f) {
    var hop = function (role) { return f.hops.filter(function (h) { return h.role === role; })[0]; };
    var said = function (h) { return h ? h.model + " (" + h.provider + "), " + h.seconds + " s, " + usd(h.cost, 3) : ""; };
    var steps = [
      { name: "Capture", title: f.failing.length + " failing tests", body: function () {
        return [para("The pull request's tests failed on the build server. mend reran the whole suite in a sealed container with no network and captured each failure as a record. These are the failing tests:"), list(f.failing.map(function (t) { return el("code", null, t); }), "plain compact")];
      } },
      { name: "Group", title: f.tickets.length + " tickets", body: function () {
        return [para("Failures with the same cause were grouped into one ticket. The biggest ticket goes first; one ticket per run, so a run that fails five ways does not spend five times."), ticketBars(f.tickets)];
      } },
      { name: "Locate", title: "Where to look", body: function () {
        return [para("The small, cheap model read the ticket and named the files most likely at fault, in order (" + said(hop("localiser")) + "):"), list(f.suspects.map(function (s) { return el("code", null, s); }), "plain")];
      } },
      { name: "Prove", title: "A test that fails first", body: function () {
        return [para("Before any fix, the tester wrote a new test, " + f.test_id + ", and ran it on the broken code. It had to fail there, or the run would have stopped (" + said(hop("tester")) + ")."), code(f.test_source), para("What the sandbox printed when the test ran on the broken code:"), code(f.test_output)];
      } },
      { name: "Fix", title: "The fix", body: function () {
        return [para("The fixer changed one line. The new test passes with it, and so do the existing tests nearest the change: " + f.suite.join(", ") + " (" + said(hop("fixer")) + ")."), code(f.diff, true)];
      } },
      { name: "Challenge", title: f.agrees ? "The reviewer accepted it" : "The reviewer objected", body: function () {
        var out = [para("A model from another company (" + f.reviewer + ", against a " + f.fixer + " fixer) was asked to find what is wrong with the fix (" + said(hop("reviewer")) + ").")];
        out.push(para(f.agrees ? "It found nothing wrong and accepted the fix." : "It objected: " + f.objection));
        return out;
      } },
      { name: "Route", title: "A comment on the pull request", body: function () {
        var p = el("p");
        p.appendChild(document.createTextNode("Every check passed, so the router rated it ready to offer as a pull request (" + f.tier.replace("_", " ") + ", score " + f.score + "). On live repositories this workflow only comments, so it posted the fix, the test and the review as "));
        p.appendChild(link(f.pull_request, "a comment on the pull request"));
        p.appendChild(document.createTextNode(". Total: " + usd(f.cost) + " and " + f.seconds + " seconds. A person reads it and decides."));
        return [p];
      } }
    ];
    var nav = clear(byId("follow-steps"));
    var panel = byId("follow-panel");
    var buttons = [];
    var show = function (index) {
      buttons.forEach(function (b, i) {
        b.setAttribute("aria-selected", i === index ? "true" : "false");
        b.setAttribute("tabindex", i === index ? "0" : "-1");
      });
      clear(panel);
      panel.appendChild(el("h3", null, (index + 1) + ". " + steps[index].title));
      steps[index].body().forEach(function (node) { panel.appendChild(node); });
      var foot = el("p", { "class": "step-nav" });
      if (index > 0) {
        var back = el("button", { type: "button", "class": "step-move" }, "Previous: " + steps[index - 1].name);
        back.addEventListener("click", function () { show(index - 1); buttons[index - 1].focus(); });
        foot.appendChild(back);
      }
      if (index < steps.length - 1) {
        var next = el("button", { type: "button", "class": "step-move next" }, "Next: " + steps[index + 1].name);
        next.addEventListener("click", function () { show(index + 1); buttons[index + 1].focus(); });
        foot.appendChild(next);
      }
      panel.appendChild(foot);
    };
    steps.forEach(function (s, i) {
      var b = el("button", { type: "button", role: "tab", id: "step-" + i, "aria-controls": "follow-panel" });
      b.appendChild(el("span", { "class": "step" }, String(i + 1)));
      b.appendChild(document.createTextNode(s.name));
      b.addEventListener("click", function () { show(i); });
      b.addEventListener("keydown", function (e) {
        var to = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
        if (to !== null && to >= 0 && to < steps.length) { e.preventDefault(); show(to); buttons[to].focus(); }
      });
      buttons.push(b);
      nav.appendChild(b);
    });
    show(0);
  }

  /* The animation: one real run, step by step ------------------------------------------
     A drawn sequence, not a video: the failures are dots that move as the pipeline handles
     them, and each step's detail fades in beside them. Every count, file name, line of code
     and verdict comes from the run's record in data.json. It plays when it scrolls into view,
     loops, and can be paused or stepped; with reduced motion it waits for the reader. */

  function flow(f) {
    var host = byId("flow");
    if (!host) { return; }
    var H = 400, top = 18, nodeW = 98, gap = 8, x0 = 20;
    var names = ["Tests fail", "Capture", "Group", "Locate", "Prove", "Fix", "Challenge", "Comment"];
    var root = frame(H, "Animation: a failing pull request becomes a reviewed fix, step by step");
    root.setAttribute("class", "flow-svg");

    /* The row of stages, and the progress line under it. */
    root.appendChild(svg("rect", { x: x0, y: top + 21, width: names.length * (nodeW + gap) - gap, height: 2, "class": "flow-track" }));
    var progress = svg("rect", { x: x0, y: top + 20, width: names.length * (nodeW + gap) - gap, height: 4, rx: 2, "class": "flow-progress" });
    root.appendChild(progress);
    var nodes = names.map(function (name, i) {
      var g = svg("g", { "class": "flow-node" });
      g.appendChild(svg("rect", { x: x0 + i * (nodeW + gap), y: top, width: nodeW, height: 44, rx: 8 }));
      g.appendChild(svg("text", { x: x0 + i * (nodeW + gap) + nodeW / 2, y: top + 27, "text-anchor": "middle" }, name));
      root.appendChild(g);
      return g;
    });

    /* Which dot belongs to which ticket, where the tickets sit, and the opening scatter. */
    var owner = [];
    f.tickets.forEach(function (t, ti) { for (var k = 0; k < t.size; k++) { owner.push([ti, k]); } });
    var n = owner.length;
    var pileX = function (ti) { return 150 + ti * (600 / Math.max(1, f.tickets.length - 1)); };
    var scatter = [];
    for (var i = 0; i < n; i++) {
      var a = (i * 137.5) * Math.PI / 180, r = 40 + (i * 53) % 110;
      scatter.push([440 + Math.cos(a) * r * 2.2, 265 + Math.sin(a) * r * 0.7]);
    }

    function layer() { var g = svg("g", { "class": "flow-layer" }); root.appendChild(g); return g; }
    function label(g, x, y, text, cls, anchor) { g.appendChild(svg("text", { x: x, y: y, "text-anchor": anchor || "start", "class": cls || "flow-text" }, text)); }
    function card(g, x, y, w, h, cls) { g.appendChild(svg("rect", { x: x, y: y, width: w, height: h, rx: 10, "class": cls || "flow-card" })); }
    function pill(g, x, y, text, cls) {
      var w = text.length * 7.4 + 28;
      g.appendChild(svg("rect", { x: x, y: y, width: w, height: 28, rx: 14, "class": "flow-pill " + cls }));
      g.appendChild(svg("text", { x: x + w / 2, y: y + 19, "text-anchor": "middle", "class": "flow-pill-text " + cls }, text));
      return w;
    }

    var company = function (p) { return { anthropic: "Anthropic", openai: "OpenAI", google: "Google" }[p] || p; };
    var layers = names.map(function () { return layer(); });
    var lead = f.tickets[0];
    var fixedFile = (String(f.diff).match(/^diff --git a\/(\S+)/m) || [])[1] || "";
    var diffLines = String(f.diff).split("\n").filter(function (l) { return /^[-+]/.test(l) && !/^(---|\+\+\+)/.test(l); });
    var testDefs = String(f.test_source).split("\n").filter(function (l) { return /^def /.test(l); }).map(function (l) { return l.replace(/ -> None:$/, "").replace(/:$/, ""); });

    /* 0: the failures arrive. */
    label(layers[0], 440, 110, "Pull request in " + f.repo + ": " + n + " tests fail", "flow-title", "middle");
    /* 1: captured in the sandbox. */
    card(layers[1], 230, 92, 420, 270, "flow-box");
    label(layers[1], 440, 116, "Rerun in a sealed container, network off", "flow-title", "middle");
    label(layers[1], 440, 350, n + " records: the error, the test, where it failed", "flow-text faint", "middle");
    /* 2: grouped into tickets. */
    label(layers[2], 440, 110, n + " failures, " + f.tickets.length + " tickets; the biggest goes first", "flow-title", "middle");
    f.tickets.forEach(function (t, ti) {
      label(layers[2], pileX(ti), 362, "ticket " + (ti + 1), ti === 0 ? "flow-text strong" : "flow-text faint", "middle");
      label(layers[2], pileX(ti), 380, t.size + (t.size === 1 ? " failure" : " failures"), "flow-text faint", "middle");
    });
    /* Ticket 1 stays on the left from here on. */
    var tag = layer();
    label(tag, 95, 372, "ticket 1", "flow-text strong", "middle");
    /* 3: locate. */
    label(layers[3], 230, 112, "Files most likely at fault, in order", "flow-title");
    f.suspects.forEach(function (s, si) {
      var y = 150 + si * 44;
      card(layers[3], 230, y - 24, 380, 34, s === fixedFile ? "flow-card hot" : "flow-card");
      label(layers[3], 248, y - 2, (si + 1) + ".  " + s, "flow-mono");
      if (s === fixedFile) { label(layers[3], 625, y - 2, "the fix lands here", "flow-text strong"); }
    });
    /* 4: prove. */
    card(layers[4], 230, 96, 560, 166);
    label(layers[4], 252, 126, f.test_id, "flow-mono strong");
    testDefs.slice(0, 3).forEach(function (d, di) { label(layers[4], 252, 160 + di * 30, d, "flow-mono"); });
    pill(layers[4], 230, 282, "fails on the broken code", "bad");
    label(layers[4], 230, 340, "No failing test, no fix: otherwise the run stops here.", "flow-text faint");
    /* 5: fix. */
    card(layers[5], 230, 96, 600, 120);
    label(layers[5], 252, 124, fixedFile, "flow-mono strong");
    diffLines.slice(0, 4).forEach(function (l, li) { label(layers[5], 252, 154 + li * 26, l.replace(/\s+/g, " ").slice(0, 74), l.charAt(0) === "+" ? "flow-mono add" : "flow-mono del"); });
    var w5 = pill(layers[5], 230, 240, "the new test passes", "good");
    pill(layers[5], 230 + w5 + 12, 240, "the existing tests still pass", "good");
    /* 6: challenge. */
    card(layers[6], 230, 110, 200, 90);
    label(layers[6], 330, 148, "Fix written by", "flow-text faint", "middle");
    label(layers[6], 330, 176, company(f.fixer), "flow-title", "middle");
    card(layers[6], 620, 110, 200, 90);
    label(layers[6], 720, 148, "Reviewed by", "flow-text faint", "middle");
    label(layers[6], 720, 176, company(f.reviewer), "flow-title", "middle");
    layers[6].appendChild(svg("line", { x1: 444, x2: 600, y1: 155, y2: 155, "class": "flow-arrow" }));
    layers[6].appendChild(svg("path", { d: "M600 149 L610 155 L600 161 Z", "class": "flow-arrowhead" }));
    label(layers[6], 525, 143, "find what is wrong", "flow-text faint", "middle");
    pill(layers[6], 620, 222, f.agrees ? "accepted" : "objected", f.agrees ? "good" : "bad");
    /* 7: comment. */
    card(layers[7], 230, 96, 560, 150, "flow-card comment");
    label(layers[7], 252, 128, "mend commented on the pull request", "flow-title");
    label(layers[7], 252, 162, "The fix, the test that failed first, and the review", "flow-text");
    label(layers[7], 252, 192, "Rated ready to propose; posted as a suggestion", "flow-text");
    label(layers[7], 252, 222, usd(f.cost) + " in model calls, " + f.seconds + " seconds", "flow-text faint");
    pill(layers[7], 230, 266, "Nothing merges. A person decides.", "neutral");

    /* The dots: one per failing test. */
    var dots = owner.map(function (o) {
      var c = svg("circle", { cx: 0, cy: 0, r: 9, "class": "flow-dot" + (o[0] === 0 ? " lead" : "") });
      root.appendChild(c);
      return c;
    });
    function place(c, x, y) { c.style.transform = "translate(" + x.toFixed(1) + "px, " + y.toFixed(1) + "px)"; }

    var captions = [
      "A pull request's tests fail on the build server: " + n + " failing tests, some of them symptoms of the same bug.",
      "mend reruns the whole suite in a sealed container with no network, and turns each failure into a record.",
      "Failures with one cause become one ticket. " + n + " failures become " + f.tickets.length + " tickets, and the biggest, " + lead.size + " failures, goes first.",
      "A small, cheap model reads the ticket and lists the files most likely at fault.",
      "Before any fix, a new test that shows the bug must fail on the broken code. Here it did.",
      "The fixer changes one line. The new test now passes, and so do the existing tests nearest the change.",
      "A model from another company (" + company(f.reviewer) + ", against an " + company(f.fixer) + " fixer) is asked to find what is wrong with the fix. It " + (f.agrees ? "found nothing and accepted it." : "objected: " + f.objection),
      "Every check passed, so mend posted the fix, its test and the review on the pull request, for " + usd(f.cost) + ". Nothing merges: a person decides."
    ];

    var step = 0;
    function show(s) {
      step = s;
      nodes.forEach(function (g, i) { g.setAttribute("class", "flow-node" + (i < s ? " done" : i === s ? " on" : "")); });
      progress.style.transform = "scaleX(" + ((s + 1) / names.length).toFixed(3) + ")";
      layers.forEach(function (g, i) { g.setAttribute("class", "flow-layer" + (i === s ? " show" : "")); });
      tag.setAttribute("class", "flow-layer" + (s >= 3 ? " show" : ""));
      dots.forEach(function (c, i) {
        var o = owner[i], ti = o[0], k = o[1];
        var cls = "flow-dot" + (ti === 0 ? " lead" : "");
        if (s === 0) { place(c, scatter[i][0], scatter[i][1]); }
        else if (s === 1) { place(c, 330 + (i % 5) * 55, 185 + Math.floor(i / 5) * 80); }
        else if (s === 2) { place(c, pileX(ti), 330 - k * 26); }
        else {
          if (ti === 0) { place(c, 95, 340 - k * 26); } else { place(c, pileX(ti), 330 - k * 26); cls += s === 3 ? " faded" : " gone"; }
          if (ti === 0 && s >= 5) { cls += " fixed"; }
        }
        c.setAttribute("class", cls);
      });
      byId("flow-caption").textContent = (s + 1) + ". " + names[s] + ": " + captions[s];
      byId("flow-count").textContent = "Step " + (s + 1) + " of " + names.length;
    }

    clear(host).appendChild(root);
    var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var playing = false, timer = null, button = byId("flow-play");
    function tick() { show(step === names.length - 1 ? 0 : step + 1); timer = setTimeout(tick, step === names.length - 1 ? 7000 : 4200); }
    function play() { if (playing) { return; } playing = true; button.textContent = "Pause"; timer = setTimeout(tick, 4200); }
    function pause() { playing = false; button.textContent = "Play"; if (timer) { clearTimeout(timer); timer = null; } }
    button.addEventListener("click", function () { if (playing) { pause(); } else { play(); } });
    byId("flow-next").addEventListener("click", function () { pause(); show(Math.min(names.length - 1, step + 1)); });
    byId("flow-back").addEventListener("click", function () { pause(); show(Math.max(0, step - 1)); });
    show(0);
    pause();
    if (!still && "IntersectionObserver" in window) {
      var seen = false;
      new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting && !seen) { seen = true; play(); }
          else if (!e.isIntersecting && playing) { pause(); seen = false; }
        });
      }, { threshold: 0.45 }).observe(host);
    }
  }

  /* Loading ------------------------------------------------------------------------ */

  function fail(message) {
    var box = byId("failure");
    if (box) { box.textContent = message; box.hidden = false; }
  }

  function draw(data) {
    flow(data.follow);
    follow(data.follow);

    var chaos = data.clustering.chaos.map(function (c, i) { return { label: c.label, value: c.value, cls: i === 2 ? "seq0" : "seq2" }; });
    bars("chaos-chart", "chaos-readout", chaos, { title: "Agreement with the true faults on project 09's breakdowns, by clustering method", format: ari, tick: function (v) { return v.toFixed(1); }, max: 1, spread: true });

    var sets = data.clustering.sets.map(function (s) { return { label: s.label, value: s.ari, cls: "seq1", note: s.causes + " causes, " + s.symptoms + " symptoms" }; });
    bars("sets-chart", "sets-readout", sets, { title: "Agreement with the true causes on two more labelled sets, one record at a time", format: ari, tick: function (v) { return v.toFixed(1); }, max: 1, left: 330 });

    var arms = data.test_first.arms.map(function (a, i) { return { label: a.label, value: a.resolved, cls: i === 0 ? "seq0" : "seq2", note: "model cost " + usd(a.cost, 3) + " per bug" }; });
    bars("testfirst-chart", "testfirst-readout", arms, { title: "Share of the same bugs fixed with and without the failing-test step", format: function (v) { return pct(v, 0); }, max: 1 });

    var split = data.review.split.map(function (s, i) { return { label: s.label, value: s.value, cls: i === 0 ? "warnbar" : "seq1" }; });
    bars("review-chart", "review-readout", split, { title: "Share of reviewed fixes that failed the hidden tests, by the reviewer's verdict", format: function (v) { return pct(v, 0); }, max: 0.7 });

    pairedBars("reviewers-chart", "reviewers-readout", data.review.arms, [
      { key: "caught", label: "caught", cls: "seq0" },
      { key: "false_alarm", label: "false alarm", cls: "warnbar" }
    ], { title: "How often each reviewer objected to wrong fixes and to right ones", format: function (v) { return pct(v, 0); }, max: 1, left: 280 });
    legend("reviewers-legend", [["solid sw-seq0", "caught: objected to a wrong fix"], ["solid sw-warnbar", "false alarm: objected to a right fix"]]);

    var tiers = data.resolution.tiers.map(function (t, i) { return { label: t.tier + " (" + t.n + ")", value: t.hit, cls: ["seq0", "seq1", "seq2"][i] }; });
    bars("tiers-chart", "tiers-readout", tiers, { title: "Share fixed in each routing group", format: function (v) { return pct(v, 0); }, max: 1, baseline: data.resolution.all.hit.est, baselineLabel: "all " + data.resolution.all.n + ": " + pct(data.resolution.all.hit.est) });

    var causes = data.wrong.causes.map(function (c) { return { label: c.cause, value: c.share, cls: c.count ? "seq0" : "seq2", note: c.count + " of " + c.share.n + ": " + c.meaning }; });
    bars("causes-chart", "causes-readout", causes, { title: "Why each confidently wrong fix failed, by cause", format: function (v) { return pct(v, 0); }, max: 1, left: 230 });

    resultRows(data.resolution);
    caseRows(data.wrong);
    liveRows(data.live);
  }

  fetch("data.json", { cache: "no-cache" })
    .then(function (response) {
      if (!response.ok) { throw new Error("data.json: HTTP " + response.status); }
      return response.json();
    })
    .then(draw)
    .catch(function (error) {
      fail("The charts could not load (" + error.message + "). Every number is also in the repository's README.");
    });
})();
