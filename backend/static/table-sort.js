/* Click a column header, or press Enter on it, to sort a table. Cells carry a
   data-sort-value; an empty value is missing data and always sorts last.
   Without JavaScript the table stays in period order. */
(function () {
  function compare(a, b, ascending) {
    var missingA = a === "", missingB = b === "";
    if (missingA || missingB) return missingA === missingB ? 0 : missingA ? 1 : -1;
    var na = Number(a), nb = Number(b);
    var result = isNaN(na) || isNaN(nb) ? (a < b ? -1 : a > b ? 1 : 0) : na - nb;
    return ascending ? result : -result;
  }

  function sortBy(table, index, ascending) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    var keyed = rows.map(function (row, position) {
      return { row: row, position: position, value: row.cells[index].getAttribute("data-sort-value") || "" };
    });
    keyed.sort(function (x, y) {
      return compare(x.value, y.value, ascending) || x.position - y.position;
    });
    keyed.forEach(function (item) { body.appendChild(item.row); });
  }

  function setup(table) {
    if (table.getAttribute("data-sort-ready")) return;
    table.setAttribute("data-sort-ready", "true");
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, index) {
      th.tabIndex = 0;
      th.style.cursor = "pointer";
      function activate() {
        var ascending = th.getAttribute("aria-sort") !== "ascending";
        Array.prototype.forEach.call(th.parentNode.cells, function (other) {
          other.setAttribute("aria-sort", "none");
        });
        th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        sortBy(table, index, ascending);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); activate(); }
      });
    });
  }

  function init(root) {
    root.querySelectorAll("table[data-sortable]").forEach(setup);
  }

  if (window.htmx) window.htmx.onLoad(init);
  else document.addEventListener("DOMContentLoaded", function () { init(document); });
})();
