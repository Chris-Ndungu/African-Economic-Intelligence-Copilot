# Vendored files

Third-party browser files, committed exactly as downloaded from their
official release and never edited. They are served from `/static/vendor/`,
so the app works offline and the browser makes no third-party request.

Each file has its exact version in its name and one row in the table below.
`tests/test_web.py` recomputes the SHA-256 of every file in this folder and
fails if a file differs from its row, or if a file has no row. To add or
upgrade a file: download it from a pinned URL, put the version in the file
name, add or update its row, and remove the old file.

| File | Version | Source URL | SHA-256 |
|---|---|---|---|
| `htmx-2.0.11.min.js` | htmx 2.0.11 | https://unpkg.com/htmx.org@2.0.11/dist/htmx.min.js | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |
| `plotly-basic-2.35.2.min.js` | plotly.js basic 2.35.2 | https://cdn.plot.ly/plotly-basic-2.35.2.min.js | `138c2e81014b979dc00867a93da55b7605a17495ee78dd7afb433b7f021dfcfa` |
| `htmx-ext-sse-2.2.2.js` | htmx SSE extension 2.2.2 | https://unpkg.com/htmx-ext-sse@2.2.2/sse.js | `83eca6fa0611fe2b0bf1700b424b88b5eced38ef448ef9760a2ea08fbc875611` |
