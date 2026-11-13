# Deployment

The app runs as one container on two free Render web services, **dev**
(`copilot-dev`) and **prod** (`copilot-prod`). GitHub Actions builds the image
once, pushes it to GHCR, and deploys it. Each environment has its own Neon
database and its own secrets. The decision is in
[plan.md](plan.md#411-containerization-and-deployment).

No step needs a billing account or a card.

## Free-tier limits that affect the app

| Service | Limit | Effect |
| --- | --- | --- |
| Render free web service | Sleeps after about 15 minutes without traffic; waking takes about a minute | The first visit after a pause is slow. Nothing pings the services to keep them awake |
| Render free web service | 512 MB of memory | The PDF export may show "Chart could not be rendered" if Chrome runs out of memory (result recorded below) |
| Render free web service | 750 free instance hours a month, shared by the workspace | Two services awake all month exceed it; services sleep when idle, so normal use fits. At the limit, all free services are suspended until the next month |
| Render free web service | No pre-deploy command | Migrations run from the deploy workflow, not from Render |
| Neon free plan | Small storage and compute allowance per project; compute scales to zero after idle | The first query after a pause is slower. Check the current numbers on neon.com/pricing |
| GitHub Actions and GHCR | Free for public repositories | None for this app |

## Can a free Render service run an image from GHCR?

Checked against Render's documentation on 2026-11-13:

- A Blueprint service can use `runtime: image` with `plan: free` (the example in
  the Blueprint reference does), and Render can pull public images from any
  registry it can reach.
- The deploy hook accepts an `imgURL` query parameter that names a tag or
  digest. Everything before the tag must match the service's image URL. The
  hook answers `200` with the new deploy's ID, or `202` when a deploy is
  already running.
- Image services never redeploy by themselves, which is what the workflows
  rely on (`autoDeployTrigger: "off"`).

The documentation does not state in one sentence that free instances may run
image services, so the final confirmation is the first deploy in "Deploy dev
by hand" below. **Record the result here after that deploy:**

- Free service runs a GHCR image: _not yet confirmed_
- Deploy hook accepts `imgURL`: _not yet confirmed_

### Fallback if either answer is no

Render builds the repository's `Dockerfile` itself at a given commit:

1. In `render.yaml`, replace `runtime: image` and `image:` with `runtime: docker`,
   `repo: https://github.com/Chris-Ndungu/African-Economic-Intelligence-Copilot`,
   `branch: main` and `autoDeployTrigger: "off"`.
2. In the workflows, skip the GHCR build and call the hook with `&ref=<full commit SHA>`
   instead of `&imgURL=...`; roll back with the previous commit's SHA.
3. The migration step still needs an image. Build it on the runner
   (`docker build -t copilot .`) and run `alembic upgrade head` with it.

The free build has the same 512 MB limit; if the build runs out of memory,
the image path (GHCR) is the only free option, and the project would need
another free host.

## Set up from empty accounts

Secret values are typed only into the Render, Neon or GitHub web pages, or
piped to `gh secret set`. They are never pasted into a chat, a file or the
shell history.

1. **Accounts.** Sign up for GitHub, Render (<https://render.com>, sign in with GitHub) and Neon
   (<https://neon.com>). Choose the free plan each time and add no card.
2. **GHCR package.** The first run of Deploy dev (or "Deploy dev by hand") pushes
   `ghcr.io/chris-ndungu/african-economic-intelligence-copilot`. Then open
   GitHub -> your profile -> Packages -> the package -> Package settings:
   - Confirm it is linked to this repository (the `org.opencontainers.image.source`
     label does that).
   - Change visibility to **Public**, so Render pulls without credentials.
3. **Neon.** Create one project in the region closest to Render Frankfurt
   (AWS `eu-central-1`). In the SQL editor create two roles and two databases,
   typing each password in the editor only:

   ```sql
   CREATE ROLE copilot_dev LOGIN PASSWORD '<typed in the editor>';
   CREATE ROLE copilot_prod LOGIN PASSWORD '<typed in the editor>';
   CREATE DATABASE copilot_dev OWNER copilot_dev;
   CREATE DATABASE copilot_prod OWNER copilot_prod;
   REVOKE CONNECT ON DATABASE copilot_dev FROM PUBLIC;
   REVOKE CONNECT ON DATABASE copilot_prod FROM PUBLIC;
   ```

   `REVOKE ... FROM PUBLIC` is what stops each role from connecting to the
   other's database; owners can still connect to their own. Test it: connecting
   as `copilot_dev` to `copilot_prod` must be refused.
4. **Connection strings.** In Neon, copy each database's **pooled** connection
   string (the host contains `-pooler`) and change the start to
   `postgresql+psycopg://` and the end to `?sslmode=require`. These are the
   `DATABASE_URL` values.
5. **Gemini keys.** Create two keys in Google AI Studio (free tier, no billing),
   one for dev and one for prod.
6. **Render Blueprint.** In Render, New -> Blueprint -> pick this repository. Render
   reads [render.yaml](../render.yaml), creates `copilot-dev` and `copilot-prod`
   and asks for each `sync: false` value. Enter each service's own
   `DATABASE_URL`, `COPILOT_GEMINI_API_KEY` and `COPILOT_RATE_LIMIT_SALT` (any
   long random string, different for each). The services need an image to start,
   so create them after the package exists and is public (step 2).
7. **Render API key.** Account Settings -> API Keys -> Create. It reaches the
   **whole Render account**, not one service, which is why it lives only in
   GitHub Environment secrets and never in a repository secret or a file.
8. **GitHub Environments.** `dev` (deploys only from `main`) and `prod` (only tags
   matching `v*`; approval by the repository owner) are already created. Each needs
   four secrets (Settings -> Environments -> the environment -> Secrets, or
   `gh secret set NAME --env dev` and type the value at the prompt):

   | Secret | Where the value comes from |
   | --- | --- |
   | `RENDER_DEPLOY_HOOK_URL` | Render service -> Settings -> Deploy Hook (the URL is a secret) |
   | `RENDER_SERVICE_ID` | The `srv-...` part of the service's dashboard URL |
   | `RENDER_API_KEY` | Step 7 (the same key in both environments) |
   | `DATABASE_URL` | Step 4, for this environment's database, used for migrations |

   GitHub withholds Environment secrets from pull requests from forks.
9. **Check the secrets.** Merge any commit to `main`. The first step of Deploy dev
   prints `NAME: set` for each secret, or an error naming the one that is
   missing, and never a value.

## Deploy dev by hand

Do this once, before relying on the workflow.

1. Build and push the image for a commit (the workflow does the same):

   ```
   gh auth refresh -s write:packages
   gh auth token | docker login ghcr.io -u Chris-Ndungu --password-stdin
   docker build -t ghcr.io/chris-ndungu/african-economic-intelligence-copilot:$(git rev-parse HEAD) .
   docker push ghcr.io/chris-ndungu/african-economic-intelligence-copilot:$(git rev-parse HEAD)
   ```

   Make the package public (setup step 2).
2. Apply the migrations with the image. Type the URL at the prompt so it is not
   in the shell history:

   ```
   read -rs DATABASE_URL && export DATABASE_URL
   docker run --rm -e DATABASE_URL ghcr.io/chris-ndungu/african-economic-intelligence-copilot:$(git rev-parse HEAD) alembic upgrade head
   ```

   The `investigations` table now exists.
3. Create the Blueprint services (setup step 6). In `copilot-dev` -> Settings, set
   the image tag to the commit SHA if Render shows another tag, and deploy.
4. Check at the dev URL:
   - `/health` returns 200; the workspace loads and shows the sample-data banner.
   - After 15+ minutes idle, the first visit loads within 90 seconds.
   - Run an investigation from selections; it appears in history and reopens
     after a reload. One that runs up to 90 seconds streams to the end through
     Render's proxy without being buffered.
   - Export it as PDF. Record here whether charts render or show "Chart could not be
     rendered" within 512 MB: _not yet recorded_.
   - Set an invalid Gemini key in Render, redeploy, run: the Gemini-unavailable
     message appears, not a failure page. Restore the key.
   - Render's logs contain no secret values.
   - Look at `X-Forwarded-For` behaviour: from two networks, runs must count
     against separate rate limits. If they share one, change
     `COPILOT_TRUSTED_PROXY_HOPS`.
5. Record the dev URL here. Expected: <https://copilot-dev.onrender.com> (_confirm after step 3_).

Settings in Render: `COPILOT_DEPLOYMENT_ENVIRONMENT=dev` (the setting
`COPILOT_ENVIRONMENT` only accepts `local`, `test` and `prod`, so dev leaves it
at its default), the data mode is `demo` (the bundled snapshot; there is no
live mode yet), `LLM_CLIENT=gemini`. Render provides `PORT`; the image listens on it.

## Automatic deploy to dev

[deploy-dev.yml](../.github/workflows/deploy-dev.yml) runs after the CI workflow passes
for a commit on `main` (never for pull requests or forks). It:

1. Builds the image and pushes it to GHCR as the full commit SHA (and `latest`), with
   the workflow's `GITHUB_TOKEN`. No other registry credential exists.
2. In the `dev` Environment: records the image `copilot-dev` runs now (Render API),
   runs `alembic upgrade head` with the new image against the dev database (a failure
   stops here and the service is untouched), calls the deploy hook with the new image
   and waits up to 10 minutes for the deploy to be live.
3. Smoke-tests `/health` (200) and `/api/meta` (`data_mode: demo`) for up to 3 minutes.
4. On a failed deploy or smoke test, redeploys the recorded image and ends red.
5. Writes the image tag, Render deploy ID and URL to the run summary.

Deploys queue one at a time and a started deploy is never cancelled. If several
merges arrive while one deploys, only the newest waits; it contains the others.
Secrets are passed as environment variables, never echoed, and GitHub masks them.
The shared steps are in [.github/scripts/render-deploy.sh](../.github/scripts/render-deploy.sh).

### Roll back by hand

Redeploy an earlier commit's image: in `copilot-dev` (or `copilot-prod`) on Render, choose
Manual Deploy -> Deploy an image with the tag of that commit's SHA (or the `v...` tag for
prod). Database migrations are not undone, so they must work with both the old and the
new code: **add first (new columns nullable or defaulted, new tables), remove in a later
release** once no running image uses what is removed.

## Release to prod

1. Choose the version: `v<major>.<minor>.<patch>`, for example `v0.1.0`. Use a commit that
   is on `main` and has already deployed to dev, so its image exists.
2. Push the tag:

   ```
   git tag v0.1.0 <commit-on-main>
   git push origin v0.1.0
   ```

3. [deploy-prod.yml](../.github/workflows/deploy-prod.yml) first checks that the commit is on
   `main` and that its image exists, and fails with a message if not. Then the `prod`
   Environment asks the repository owner for approval; rejecting it deploys nothing.
4. After approval it adds the version tag to the same image (no rebuild), records the
   image prod runs now, migrates the prod database, deploys, smoke-tests, and redeploys
   the previous image if that fails. The summary shows the version, the image digest and
   the prod URL.
5. Roll back by hand as above, with the previous version's tag.

The prod URL is expected to be <https://copilot-prod.onrender.com> (_confirm_). The app
refuses `LLM_CLIENT=stub` when `COPILOT_ENVIRONMENT=prod`.

## Secrets

- Values are only in the Render dashboard, Neon, and GitHub Environment secrets.
- `render.yaml` declares secrets with `sync: false`, so it holds no value.
- Dev and prod share no secret except the Render API key, which is account-wide and
  stored only as an Environment secret.
- Rotate a secret by changing it in the place above and redeploying.
