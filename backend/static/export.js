/* The "Export PDF" button. Without this script it is a plain link to the export
   endpoint and the browser downloads the file. With it, the file is fetched and
   saved here, so the button can show a loading state and a message if the export
   fails (HTMX swaps HTML and cannot save a download). The server decides every
   message; the wording comes from the table rendered into the page. */
(function () {
  function messageText(code) {
    var tag = document.getElementById("error-messages");
    try {
      return JSON.parse(tag.textContent)[code].text;
    } catch (e) {
      return "The report could not be exported (error code: " + code + "). Try again.";
    }
  }

  function filenameFrom(response, fallback) {
    var header = response.headers.get("Content-Disposition") || "";
    var match = /filename="([^"]+)"/.exec(header);
    return match ? match[1] : fallback;
  }

  function save(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
  }

  function setBusy(button, busy) {
    if (busy) {
      button.setAttribute("data-label", button.textContent);
      button.textContent = "Exporting…";
      button.setAttribute("aria-disabled", "true");
      button.setAttribute("aria-busy", "true");
      button.classList.add("is-loading");
    } else {
      button.textContent = button.getAttribute("data-label") || "Export PDF";
      button.removeAttribute("aria-disabled");
      button.removeAttribute("aria-busy");
      button.classList.remove("is-loading");
    }
  }

  function showError(box, code) {
    if (!box) return;
    box.textContent = messageText(code);
    box.hidden = false;
  }

  function errorCode(response) {
    return response.json().then(
      function (body) { return (body && body.code) || "internal_error"; },
      function () { return "internal_error"; }
    );
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("a.export-pdf");
    if (!button) return;
    if (!window.fetch || !window.URL || !URL.createObjectURL) return; // the link works as is
    event.preventDefault();
    if (button.getAttribute("aria-disabled") === "true") return;
    var box = button.parentNode.querySelector(".export-error");
    if (box) box.hidden = true;
    setBusy(button, true);
    fetch(button.getAttribute("href"), { headers: { Accept: "application/pdf" } })
      .then(function (response) {
        if (!response.ok) {
          return errorCode(response).then(function (code) { showError(box, code); });
        }
        return response.blob().then(function (blob) {
          save(blob, filenameFrom(response, "investigation.pdf"));
        });
      })
      .catch(function () { showError(box, "connection_lost"); })
      .then(function () { setBusy(button, false); });
  });
})();
