/* History sidebar behaviour: highlight the open investigation and let error
   pages replace the main panel. The sidebar itself is rendered by the server. */
(function () {
  function highlight() {
    var path = window.location.pathname;
    document.querySelectorAll("#history .history-item a").forEach(function (link) {
      if (link.getAttribute("href") === path) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  ["htmx:pushedIntoHistory", "htmx:historyRestore", "htmx:afterSettle"].forEach(function (name) {
    document.addEventListener(name, highlight);
  });
  document.addEventListener("DOMContentLoaded", highlight);

  // A 404 or 503 answer to a click carries the "Not found" or "unavailable" panel.
  document.addEventListener("htmx:beforeSwap", function (event) {
    var status = event.detail.xhr && event.detail.xhr.status;
    if ((status === 404 || status === 503) && event.detail.target && event.detail.target.id === "workspace") {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
})();
