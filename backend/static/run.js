/* Run form and live progress behaviour: the character counter, the run button
   rules, Enter to submit, Cancel and the lost-connection check. The server
   decides every message and number; this script only toggles what the page shows. */
(function () {
  var QUIET_MS = 30000;
  var timer = null;

  function byId(id) { return document.getElementById(id); }

  // The wording comes from the server, rendered once into the page.
  function messageText(code) {
    var tag = byId("error-messages");
    try {
      return JSON.parse(tag.textContent)[code].text;
    } catch (e) {
      return code;
    }
  }

  function progress() {
    var box = byId("results");
    return box && box.classList.contains("run-progress") ? box : null;
  }

  function running() {
    var box = progress();
    return !!box && !box.querySelector(".run-ended") && !box.classList.contains("is-stopped");
  }

  function refresh() {
    var question = byId("question");
    var button = byId("run-button");
    if (!question || !button) return;
    var count = byId("question-count");
    var max = Number(question.maxLength);
    if (count) {
      count.textContent = question.value.length.toLocaleString("en-US") + " / " +
        max.toLocaleString("en-US") + " characters";
    }
    var hasQuestion = question.value.trim() !== "";
    var selection = byId("selection-form");
    var hasSelection = !!selection && selection.getAttribute("data-valid-selection") === "true";
    var ready = (hasQuestion || hasSelection) && !button.hasAttribute("data-unavailable");
    var hint = byId("run-hint");
    if (hint && !hint.hasAttribute("data-sticky")) hint.hidden = ready;
    button.disabled = !ready || running();
  }

  document.addEventListener("input", function (event) {
    if (event.target && event.target.id === "question") {
      var hint = byId("run-hint");
      if (hint) hint.removeAttribute("data-sticky");
      refresh();
    }
  });

  // Enter submits the question; Shift+Enter adds a line.
  document.addEventListener("keydown", function (event) {
    if (!event.target || event.target.id !== "question") return;
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    var button = byId("run-button");
    if (button && !button.disabled) byId("run-form").requestSubmit(button);
  });

  function source(box) {
    var data = box && box["htmx-internal-data"];
    return data && data.sseEventSource;
  }

  function stop(box, text, extra) {
    clearTimeout(timer);
    var src = source(box);
    if (src) src.close();
    box.classList.add("is-stopped");
    var outcome = box.querySelector("#run-outcome");
    var note = document.createElement("div");
    note.className = "run-ended";
    var p = document.createElement("p");
    p.className = "message";
    p.textContent = text;
    note.appendChild(p);
    if (extra) note.appendChild(extra);
    if (outcome) {
      outcome.textContent = "";
      outcome.appendChild(note);
    }
    refresh();
  }

  // No event or ping for 30 seconds: the connection is lost.
  function watch(box) {
    clearTimeout(timer);
    timer = setTimeout(function () {
      if (!running()) return;
      var link = document.createElement("a");
      link.href = "/#history";
      link.textContent = "Open the history";
      var holder = document.createElement("p");
      holder.appendChild(link);
      stop(box, messageText("connection_lost"), holder);
    }, QUIET_MS);
  }

  document.addEventListener("click", function (event) {
    var cancel = event.target && event.target.closest && event.target.closest("[data-cancel-run]");
    if (!cancel) return;
    var box = progress();
    if (box) stop(box, messageText("client_disconnected"));
  });

  document.addEventListener("htmx:sseOpen", function () {
    var box = progress();
    if (box) watch(box);
    refresh();
  });
  document.addEventListener("htmx:sseMessage", function (event) {
    var box = progress();
    if (!box) return;
    if (event.detail && event.detail.type === "outcome") {
      clearTimeout(timer);
      // The run has ended and is saved: refresh the history sidebar.
      htmx.trigger(document.body, "investigation-saved");
    } else {
      watch(box);
    }
  });

  ["htmx:afterSwap", "htmx:afterSettle", "htmx:historyRestore", "htmx:beforeRequest", "DOMContentLoaded"].forEach(
    function (name) { document.addEventListener(name, refresh); }
  );
  document.addEventListener("htmx:afterSettle", function () {
    var box = progress();
    if (box && !box.hasAttribute("data-watching")) {
      box.setAttribute("data-watching", "");
      watch(box);
    }
    if (!box) clearTimeout(timer);
  });
})();
