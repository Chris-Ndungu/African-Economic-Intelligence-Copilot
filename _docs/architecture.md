# Architecture

System components, the request flow for running an investigation, data modes, and the key technical decisions as built.

Filled in by #54.

## Unsupported questions

The interpretation prompt, [`copilot_core/prompts/interpret_v1.md`](../copilot_core/prompts/interpret_v1.md), tells Gemini to decline these questions. The reply then has `unsupported_reason` set and no findings, and the run is saved as `succeeded`, so the analyst sees why. The list follows the out-of-scope features in [plan.md section 5](plan.md#5-explicitly-out-of-scope) and the limits of the data:

- a forecast or prediction of future values (forecasting is out of scope)
- proof that one indicator causes another (causal inference claims are out of scope)
- a country that is not in the data (only African countries are covered)
- an indicator that is not in the supported list (`GET /api/indicators`)
- questions that need sources outside the data, such as news or web research (external web research is out of scope)
- anything that is not about the economic data, such as advice, opinions or writing tasks

The analyst's question is passed to Gemini between `<question>` tags and treated as data, not instructions, so a question that says "ignore previous instructions" changes nothing.

## Visitors, history and limits

**Private history (#59).** A visitor with no login gets a random anonymous ID in
an HTTP-only cookie (`copilot_visitor`, `SameSite=Lax`, `Secure` in prod) on
their first request. Every saved investigation has an `owner` (`anon:<id>`),
and the repository returned to a request lists, fetches, updates and exports
only that owner's rows. Another visitor's ID answers `404`, never `403`, so IDs
cannot be probed. Clearing cookies starts an empty history; the sidebar says
history is kept in this browser only. The ID is never logged or put in
telemetry.

- **Cap:** one anonymous visitor holds at most `COPILOT_ANONYMOUS_INVESTIGATION_LIMIT`
  (default 50) investigations. Saving one more answers `409` with a message
  that names the limit.
- **Retention:** anonymous investigations older than
  `COPILOT_ANONYMOUS_RETENTION_DAYS` (default 30) are deleted when the app
  starts. Cloud Run starts instances often, so no separate scheduler is needed;
  rows saved before owners existed (`owner` is null) are not shown to anyone.
- **Logged-in users:** `owner` is free text, so a user identity (`user:<id>`)
  can key history the same way once login (#50) exists.

**Rate limits (#60).** Starting a run is limited per client
(`COPILOT_RUNS_PER_IP_PER_HOUR`, default 10) and in total
(`COPILOT_RUNS_PER_DAY_TOTAL`, default 200); authenticated users have
`COPILOT_AUTHENTICATED_RUNS_PER_HOUR` (default 60). A run over a limit is
`429` with the shared error body and a `Retry-After` header, before Gemini is
called. The JSON endpoints and the HTML run and retry routes share one count;
reading, listing and exporting are not counted. Counts are rows of the
`run_attempts` table, so they hold across Cloud Run instances; a row holds a
salted hash of the client, never the address, and is deleted once older than
the longest window.

The client is the TCP peer, unless `COPILOT_TRUSTED_PROXY_HOPS` is set: with
`1` on Cloud Run it is the `X-Forwarded-For` entry Google's front end appended
(the last one), and entries a client put before it are ignored.
