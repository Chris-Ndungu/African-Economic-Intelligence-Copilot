/* Selection panel behaviour: the country filter and the failed-update message.
   The panel itself is rendered by the server and swapped by HTMX. */
(function () {
  function applyFilter() {
    var input = document.getElementById("country-filter");
    if (!input) return;
    var needle = input.value.trim().toLowerCase();
    document.querySelectorAll(".country-list li").forEach(function (item) {
      // Hiding a row never unchecks its box: the checkbox stays in the form.
      item.hidden = needle !== "" && item.getAttribute("data-filter").indexOf(needle) === -1;
    });
  }

  document.addEventListener("input", function (event) {
    if (event.target && event.target.id === "country-filter") applyFilter();
  });
  // Typing in the filter is not a selection change, so it must not post the form.
  document.addEventListener(
    "change",
    function (event) {
      if (event.target && event.target.id === "country-filter") event.stopPropagation();
    },
    true
  );

  function setError(visible) {
    var box = document.getElementById("selection-error");
    if (box) box.hidden = !visible;
  }

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.id === "selection-panel") setError(false);
    applyFilter();
  });
  ["htmx:responseError", "htmx:sendError"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      var elt = event.detail && event.detail.elt;
      if (elt && elt.id === "selection-form") setError(true);
    });
  });
  document.addEventListener("click", function (event) {
    if (!event.target || event.target.id !== "selection-retry") return;
    var form = document.getElementById("selection-form");
    if (form && window.htmx) window.htmx.trigger(form, "change");
  });
})();
