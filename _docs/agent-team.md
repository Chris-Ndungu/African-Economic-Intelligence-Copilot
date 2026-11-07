# Agent team

The roles that build this project, what each one does, and how work moves
between them. It follows the table in section 4.14 of
[plan.md](plan.md#414-ai-assisted-development-workflow). How a single task
moves from issue to merged PR is in [process.md](process.md).

## PM

Follows [team/pm.md](team/pm.md).

- Responsibilities: turns requirements into specs and issues with
  acceptance criteria
- Inputs: `_docs/plan.md`
- Outputs: specs, groomed issues

## Backend

- Responsibilities: implements `copilot_core` and the FastAPI routes
  against the OpenAPI contract
- Inputs: a groomed issue and the OpenAPI contract
- Outputs: a backend PR

## Frontend

- Responsibilities: implements the UI in Jinja templates, HTMX partials,
  CSS and small plain-JavaScript files, rendering the same `copilot_core`
  results the JSON API returns
- Inputs: a groomed issue and the `copilot_core` result models
- Outputs: a frontend PR

## QA

Follows [team/qa-engineer.md](team/qa-engineer.md).

- Responsibilities: writes and maintains integration and Playwright tests
  from the acceptance criteria, and tests against the acceptance criteria,
  not implementation details
- Inputs: the acceptance criteria of an issue
- Outputs: a test PR

## Ops

- Responsibilities: owns CI/CD, telemetry, alerts and on-call response
- Inputs: alerts and telemetry
- Outputs: a fix PR

## Collaboration

- Work proceeds one GitHub issue at a time
- The `copilot_core` result models are the hand-off between backend and
  frontend; the OpenAPI contract is the hand-off between the API and its
  clients and tests. The contract changes before API behavior does
- A human reviews and merges every PR. No agent merges
- When two roles disagree, for example the frontend finds a result model
  is missing something it must show, nobody works around it. The issue goes back to the PM to re-groom,
  and work resumes from the updated issue
