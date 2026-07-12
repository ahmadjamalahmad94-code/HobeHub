/*
 * dashboard_table.js
 * ─────────────────────────────────────────────────────────
 * Client-side pagination + page-size selector for any <table>
 * marked with `data-paginated="1"`.
 *
 * Optional attributes on <table>:
 *   data-paginated="1"        ← required to activate
 *   data-page-size="20"       ← default page size (default: 20)
 *   data-page-sizes="10,20,50,100"  ← options for the size selector
 *
 * The script wraps the table inside the existing <div class="d-table-wrap">
 * and appends a footer controls bar after it.
 *
 * It paginates only rows in the FIRST <tbody>, ignoring rows
 * with class "no-paginate" (e.g. the "empty state" row).
 */
(function () {
  "use strict";

  function makeButton(label, opts) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dpt-btn";
    btn.innerHTML = label;
    if (opts && opts.icon) btn.classList.add("dpt-btn-icon");
    return btn;
  }

  function buildControls(state) {
    var foot = document.createElement("div");
    foot.className = "dpt-foot";

    // Left: page size selector
    var sizeBox = document.createElement("div");
    sizeBox.className = "dpt-size-box";
    var sizeLabel = document.createElement("span");
    sizeLabel.className = "dpt-size-label";
    sizeLabel.textContent = "صفوف لكل صفحة:";
    var sizeSelect = document.createElement("select");
    sizeSelect.className = "dpt-size-select";
    state.sizes.forEach(function (n) {
      var opt = document.createElement("option");
      opt.value = String(n);
      opt.textContent = String(n);
      if (n === state.pageSize) opt.selected = true;
      sizeSelect.appendChild(opt);
    });
    sizeBox.appendChild(sizeLabel);
    sizeBox.appendChild(sizeSelect);

    // Center: info
    var info = document.createElement("div");
    info.className = "dpt-info";

    // Right: pager buttons
    var pager = document.createElement("div");
    pager.className = "dpt-pager";
    var first = makeButton('<i class="fa-solid fa-angles-right"></i>', { icon: true });
    first.title = "الأولى";
    var prev = makeButton('<i class="fa-solid fa-angle-right"></i>', { icon: true });
    prev.title = "السابقة";
    var pages = document.createElement("div");
    pages.className = "dpt-pages";
    var next = makeButton('<i class="fa-solid fa-angle-left"></i>', { icon: true });
    next.title = "التالية";
    var last = makeButton('<i class="fa-solid fa-angles-left"></i>', { icon: true });
    last.title = "الأخيرة";
    pager.appendChild(first);
    pager.appendChild(prev);
    pager.appendChild(pages);
    pager.appendChild(next);
    pager.appendChild(last);

    foot.appendChild(sizeBox);
    foot.appendChild(info);
    foot.appendChild(pager);

    state.ctrl = {
      foot: foot,
      sizeSelect: sizeSelect,
      info: info,
      pages: pages,
      first: first,
      prev: prev,
      next: next,
      last: last,
    };
    return foot;
  }

  function renderPageButtons(state) {
    var p = state.page;
    var total = state.pageCount;
    state.ctrl.pages.innerHTML = "";

    if (total <= 1) return;

    function btn(num, isActive) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "dpt-page" + (isActive ? " is-active" : "");
      b.textContent = String(num);
      b.addEventListener("click", function () { goTo(state, num); });
      return b;
    }
    function ellipsis() {
      var s = document.createElement("span");
      s.className = "dpt-ellipsis";
      s.textContent = "…";
      return s;
    }

    // smart: show 1, …, p-1, p, p+1, …, total
    var nums = new Set([1, total, p - 1, p, p + 1]);
    var arr = Array.from(nums).filter(function (n) { return n >= 1 && n <= total; }).sort(function (a, b) { return a - b; });
    var prevNum = 0;
    arr.forEach(function (n) {
      if (prevNum && n - prevNum > 1) state.ctrl.pages.appendChild(ellipsis());
      state.ctrl.pages.appendChild(btn(n, n === p));
      prevNum = n;
    });
  }

  function applyPage(state) {
    var size = state.pageSize;
    var p = state.page;
    var startIdx = (p - 1) * size;
    var endIdx = startIdx + size;
    var visibleCount = 0;
    state.rows.forEach(function (tr, idx) {
      if (idx >= startIdx && idx < endIdx) {
        tr.style.display = "";
        visibleCount++;
      } else {
        tr.style.display = "none";
      }
    });

    var totalRows = state.rows.length;
    var from = totalRows === 0 ? 0 : startIdx + 1;
    var to = Math.min(endIdx, totalRows);
    state.ctrl.info.innerHTML =
      "عرض <strong>" + from + "</strong> – <strong>" + to + "</strong> " +
      "من <strong>" + totalRows + "</strong>";

    state.ctrl.first.disabled = p <= 1;
    state.ctrl.prev.disabled = p <= 1;
    state.ctrl.next.disabled = p >= state.pageCount;
    state.ctrl.last.disabled = p >= state.pageCount;

    renderPageButtons(state);

    if (state.persistKey) {
      try {
        localStorage.setItem(state.persistKey + ":size", String(state.pageSize));
      } catch (e) {}
    }
  }

  function goTo(state, p) {
    if (p < 1) p = 1;
    if (p > state.pageCount) p = state.pageCount;
    state.page = p;
    applyPage(state);
  }

  function recomputePageCount(state) {
    state.pageCount = Math.max(1, Math.ceil(state.rows.length / state.pageSize));
    if (state.page > state.pageCount) state.page = state.pageCount;
    if (state.page < 1) state.page = 1;
  }

  function attach(table) {
    if (table.__dptAttached) return;
    table.__dptAttached = true;

    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.rows).filter(function (tr) {
      return !tr.classList.contains("no-paginate");
    });

    // skip if there's only an "empty state" row or fewer rows than the smallest page
    var defaultSize = parseInt(table.getAttribute("data-page-size") || "20", 10);
    var sizesAttr = (table.getAttribute("data-page-sizes") || "10,20,50,100").split(",");
    var sizes = sizesAttr.map(function (x) { return parseInt(x.trim(), 10); }).filter(function (n) { return n > 0; });
    if (sizes.indexOf(defaultSize) === -1) sizes.unshift(defaultSize);

    var persistKey = table.getAttribute("data-persist-key") || "";
    if (persistKey) {
      try {
        var saved = parseInt(localStorage.getItem(persistKey + ":size") || "", 10);
        if (saved && sizes.indexOf(saved) !== -1) defaultSize = saved;
      } catch (e) {}
    }

    var state = {
      table: table,
      rows: rows,
      pageSize: defaultSize,
      page: 1,
      pageCount: 1,
      sizes: sizes,
      persistKey: persistKey,
      ctrl: null,
      sortCol: null,
      sortDir: null,
    };

    recomputePageCount(state);

    var foot = buildControls(state);
    // Insert footer just AFTER the table's wrapping element if it exists,
    // otherwise after the table itself.
    var wrap = table.closest(".d-table-wrap") || table;
    if (wrap.parentNode) {
      wrap.parentNode.insertBefore(foot, wrap.nextSibling);
    }

    // Hide footer when only 1 page AND a single size choice
    if (state.rows.length <= Math.min.apply(null, sizes)) {
      foot.classList.add("dpt-min");
    }

    // Wire events
    state.ctrl.sizeSelect.addEventListener("change", function () {
      var v = parseInt(state.ctrl.sizeSelect.value, 10) || defaultSize;
      state.pageSize = v;
      state.page = 1;
      recomputePageCount(state);
      applyPage(state);
    });
    state.ctrl.first.addEventListener("click", function () { goTo(state, 1); });
    state.ctrl.prev.addEventListener("click", function () { goTo(state, state.page - 1); });
    state.ctrl.next.addEventListener("click", function () { goTo(state, state.page + 1); });
    state.ctrl.last.addEventListener("click", function () { goTo(state, state.pageCount); });

    applyPage(state);
    setupSorting(state);
    setupColumnToggle(state);
  }

  // ─── Sorting ──────────────────────────────────────────────
  function headerCells(table) {
    var thead = table.tHead;
    if (!thead || !thead.rows.length) return [];
    return Array.prototype.slice.call(thead.rows[thead.rows.length - 1].cells);
  }
  function cellText(tr, idx) {
    var td = tr.cells[idx];
    return td ? (td.textContent || "").trim() : "";
  }
  function compareVals(a, b) {
    var na = parseFloat(a.replace(/[^\d.\-]/g, ""));
    var nb = parseFloat(b.replace(/[^\d.\-]/g, ""));
    var aNum = a !== "" && /\d/.test(a) && !isNaN(na);
    var bNum = b !== "" && /\d/.test(b) && !isNaN(nb);
    if (aNum && bNum) return na - nb;
    if (a === b) return 0;
    return a.localeCompare(b, "ar");
  }
  function sortBy(state, colIdx, dir) {
    state.rows.sort(function (r1, r2) {
      var c = compareVals(cellText(r1, colIdx), cellText(r2, colIdx));
      return dir === "desc" ? -c : c;
    });
    var tbody = state.table.tBodies[0];
    state.rows.forEach(function (tr) { tbody.appendChild(tr); });
    state.page = 1;
    applyPage(state);
  }
  function setupSorting(state) {
    var ths = headerCells(state.table);
    ths.forEach(function (th, idx) {
      if (th.hasAttribute("data-no-sort") || !th.textContent.trim() || th.querySelector("input")) return;
      th.classList.add("dpt-sortable");
      var ind = document.createElement("span");
      ind.className = "dpt-sort";
      ind.innerHTML = '<i class="fa-solid fa-sort"></i>';
      th.appendChild(ind);
      th.addEventListener("click", function (e) {
        if (e.target.closest(".dpt-cols-box")) return;
        var dir = (state.sortCol === idx && state.sortDir === "asc") ? "desc" : "asc";
        state.sortCol = idx; state.sortDir = dir;
        ths.forEach(function (t) { var s = t.querySelector(".dpt-sort"); if (s) s.innerHTML = '<i class="fa-solid fa-sort"></i>'; });
        ind.innerHTML = dir === "asc" ? '<i class="fa-solid fa-sort-up"></i>' : '<i class="fa-solid fa-sort-down"></i>';
        sortBy(state, idx, dir);
      });
    });
  }

  // ─── Column show/hide ─────────────────────────────────────
  function setColVisible(state, idx, visible) {
    var thead = state.table.tHead;
    if (thead) Array.prototype.forEach.call(thead.rows, function (r) { if (r.cells[idx]) r.cells[idx].style.display = visible ? "" : "none"; });
    var tbody = state.table.tBodies[0];
    if (tbody) Array.prototype.forEach.call(tbody.rows, function (r) { if (r.cells[idx]) r.cells[idx].style.display = visible ? "" : "none"; });
  }
  function loadHidden(state) {
    if (!state.persistKey) return [];
    try { return JSON.parse(localStorage.getItem(state.persistKey + ":cols") || "[]") || []; } catch (e) { return []; }
  }
  function saveHidden(state) {
    if (!state.persistKey) return;
    var ths = headerCells(state.table), hidden = [];
    ths.forEach(function (th, idx) { if (th.style.display === "none") hidden.push(idx); });
    try { localStorage.setItem(state.persistKey + ":cols", JSON.stringify(hidden)); } catch (e) {}
  }
  function setupColumnToggle(state) {
    var ths = headerCells(state.table);
    if (!ths.length) return;
    var box = document.createElement("div");
    box.className = "dpt-cols-box";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dpt-btn dpt-cols-btn";
    btn.innerHTML = '<i class="fa-solid fa-table-columns"></i> الأعمدة';
    var menu = document.createElement("div");
    menu.className = "dpt-cols-menu";
    var hidden = loadHidden(state);
    var count = 0;
    ths.forEach(function (th, idx) {
      if (th.hasAttribute("data-no-hide")) return;
      count++;
      var label = (th.textContent || "").trim() || ("عمود " + (idx + 1));
      var item = document.createElement("label");
      item.className = "dpt-cols-item";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = hidden.indexOf(idx) === -1;
      cb.addEventListener("change", function () { setColVisible(state, idx, cb.checked); saveHidden(state); });
      item.appendChild(cb);
      item.appendChild(document.createTextNode(" " + label));
      menu.appendChild(item);
      if (!cb.checked) setColVisible(state, idx, false);
    });
    if (!count) return;  // لا أعمدة قابلة للإخفاء → لا زرّ
    box.appendChild(btn);
    box.appendChild(menu);
    function positionMenu() {
      var r = btn.getBoundingClientRect();
      menu.style.top = (r.bottom + 6) + "px";
      menu.style.left = "auto";
      menu.style.right = Math.max(6, window.innerWidth - r.right) + "px";
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var willOpen = !box.classList.contains("open");
      box.classList.toggle("open");
      if (willOpen) positionMenu();
    });
    menu.addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", function () { box.classList.remove("open"); });
    window.addEventListener("scroll", function () { box.classList.remove("open"); }, true);
    window.addEventListener("resize", function () { box.classList.remove("open"); });

    // شريط علويّ فوق الجدول (خارج حاوية overflow كي تفتح القائمة فوق كل شيء بلا قصّ)
    var wrap = state.table.closest(".d-table-wrap") || state.table;
    var head = wrap.previousElementSibling;
    if (!head || !head.classList || !head.classList.contains("dpt-head")) {
      head = document.createElement("div");
      head.className = "dpt-head";
      if (wrap.parentNode) wrap.parentNode.insertBefore(head, wrap);
    }
    head.appendChild(box);
  }

  function init() {
    // كل جداول HobeHub: المُرقّمة صراحةً + أي جدول d-table (استثناء بـdata-no-enhance).
    var tables = document.querySelectorAll("table[data-paginated], table.d-table");
    tables.forEach(function (t) {
      if (t.hasAttribute("data-no-enhance")) return;
      attach(t);
    });
  }

  // public API لإعادة تهيئة الجدول بعد تعديل tbody (AJAX rerender)
  function reattach(table) {
    if (!table) return;
    var wrap = table.closest(".d-table-wrap") || table;
    // أزل الـ footer القديم
    var sib = wrap.nextSibling;
    while (sib) {
      var next = sib.nextSibling;
      if (sib.nodeType === 1 && sib.classList && sib.classList.contains("dpt-foot")) {
        sib.parentNode.removeChild(sib);
      }
      sib = next;
    }
    // أزل الشريط العلويّ القديم (كي لا يتكرّر زرّ الأعمدة)
    var prevHead = wrap.previousElementSibling;
    if (prevHead && prevHead.classList && prevHead.classList.contains("dpt-head")) {
      prevHead.parentNode.removeChild(prevHead);
    }
    table.__dptAttached = false;
    attach(table);
  }
  window.DashboardTable = { attach: attach, reattach: reattach, init: init };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
