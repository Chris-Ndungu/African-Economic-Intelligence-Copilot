/* Draws every chart element with Plotly.js. The figure is built in Python and
   sits in a <script type="application/json"> element next to the chart. */
(function () {
  function draw(root) {
    if (!window.Plotly) return;
    root.querySelectorAll(".plotly-chart").forEach(function (target) {
      if (target.getAttribute("data-drawn")) return;
      var data = target.parentNode.querySelector("script.chart-data");
      if (!data) return;
      var figure = JSON.parse(data.textContent);
      target.setAttribute("data-drawn", "true");
      window.Plotly.newPlot(target, figure.data, figure.layout, {
        responsive: true,
        displaylogo: false,
      });
    });
  }

  if (window.htmx) {
    // Runs on page load and after each HTMX swap.
    window.htmx.onLoad(draw);
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      draw(document);
    });
  }
})();
