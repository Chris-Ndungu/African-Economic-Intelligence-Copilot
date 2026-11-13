// Browser tracing for "Run investigation" (#44), hand-written and dependency-free.
//
// One span, `ui.run_investigation` (service `copilot-web`), runs from the
// moment a run request is sent until the `saved` or `failed` event arrives, or
// the run is cancelled. The run request carries a W3C `traceparent` header, so
// the server's spans join this span's trace. The span goes to this site's own
// `/otlp/v1/traces`, which forwards it; no collector address or credential is
// ever in the browser. The span records only the outcome: no question text, no
// input values, no query strings. Any failure is swallowed silently.
(function () {
  "use strict";

  var ENDPOINT = "/otlp/v1/traces";
  var RUN_REQUEST = /^\/partials\/investigations\/(run|[0-9a-f-]{36}\/retry)$/;
  var active = null;

  function hex(bytes) {
    var values = new Uint8Array(bytes);
    crypto.getRandomValues(values);
    return Array.prototype.map
      .call(values, function (value) { return ("0" + value.toString(16)).slice(-2); })
      .join("");
  }

  function now() {
    return performance.timeOrigin + performance.now();
  }

  function nanos(milliseconds) {
    return String(Math.round(milliseconds * 1e6));
  }

  function start() {
    // A new run replaces one still open: close the earlier one first.
    finish("superseded");
    active = { trace: hex(16), span: hex(8), started: now() };
    return "00-" + active.trace + "-" + active.span + "-01";
  }

  function finish(outcome) {
    var run = active;
    active = null;
    if (!run) return;
    try {
      var span = {
        traceId: run.trace,
        spanId: run.span,
        name: "ui.run_investigation",
        kind: 1,
        startTimeUnixNano: nanos(run.started),
        endTimeUnixNano: nanos(now()),
        attributes: [{ key: "run.outcome", value: { stringValue: outcome } }],
        status: { code: outcome === "failed" ? 2 : 1 }
      };
      var body = {
        resourceSpans: [{
          resource: { attributes: [{ key: "service.name", value: { stringValue: "copilot-web" } }] },
          scopeSpans: [{ scope: { name: "copilot-web" }, spans: [span] }]
        }]
      };
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        keepalive: true
      }).catch(function () {});
    } catch (ignored) {}
  }

  document.addEventListener("htmx:configRequest", function (event) {
    try {
      var detail = event.detail;
      if (String(detail.verb).toLowerCase() !== "post" || !RUN_REQUEST.test(detail.path)) return;
      detail.headers["traceparent"] = start();
    } catch (ignored) {}
  });

  document.addEventListener("htmx:sseMessage", function (event) {
    try {
      if (!active || !event.detail || event.detail.type !== "outcome") return;
      var data = String(event.detail.data || "");
      if (data.indexOf('data-outcome="saved"') !== -1) finish("saved");
      else if (data.indexOf('data-outcome="failed"') !== -1) finish("failed");
    } catch (ignored) {}
  });

  document.addEventListener("click", function (event) {
    try {
      var target = event.target;
      if (target && target.closest && target.closest("[data-cancel-run]")) finish("cancelled");
    } catch (ignored) {}
  });
})();
