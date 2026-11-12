/* Rewrite <time class="local-time" datetime="..."> in the local time zone of the browser.
   The server renders a UTC date as fallback text. The last 7 days read as
   relative ("2 hours ago"); older dates as a local date. */
(function () {
  var WEEK = 7 * 24 * 3600 * 1000;
  var UNITS = [["day", 86400000], ["hour", 3600000], ["minute", 60000]];

  function relative(ms) {
    var formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    for (var i = 0; i < UNITS.length; i++) {
      if (Math.abs(ms) >= UNITS[i][1]) return formatter.format(Math.round(-ms / UNITS[i][1]), UNITS[i][0]);
    }
    return formatter.format(0, "second");
  }

  function apply(root) {
    (root || document).querySelectorAll("time.local-time[datetime]").forEach(function (el) {
      var then = new Date(el.getAttribute("datetime"));
      if (isNaN(then.getTime())) return;
      var age = Date.now() - then.getTime();
      el.title = then.toLocaleString();
      el.textContent = age >= 0 && age < WEEK ? relative(age) : then.toLocaleDateString();
    });
  }

  document.addEventListener("DOMContentLoaded", function () { apply(document); });
  document.addEventListener("htmx:afterSettle", function (event) { apply(event.target); });
  window.localTime = apply;
})();
