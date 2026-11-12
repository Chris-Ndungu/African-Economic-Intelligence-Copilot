- Tasks are GitHub issues, worked one at a time
- Issues are grouped into the phases in
  [plan.md section 7](plan.md#7-implementation-sequence); each phase is one branch and
  one PR
- Read the acceptance criteria before starting and before closing
- Commit regularly

Roles

- PM - grooms a task before anyone implements it, follows _docs/team/pm.md
- Engineer - implements one groomed task, follows _docs/team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows _docs/team/qa-engineer.md

Orchestrator

The main session is the orchestrator. It picks the track for each issue
(below), does light-track work itself, launches the engineer as a subagent
for full-track work, and launches QA once per phase.

Every subagent starts with no context, so its brief carries what the
orchestrator already knows: the issue number, the files to read and edit,
findings and decisions made so far, and what not to re-check. A subagent
reads only what the issue and its brief point to.

Tracks

- Light track: documentation, data files, configuration, templates and
  small fixes that change no behaviour in `copilot_core` or the API. The
  orchestrator implements it and runs `uv run pytest`
- Full track: new or changed behaviour in `copilot_core`, the API or the
  UI. The engineer subagent implements it and runs the tests for it
- When in doubt, use the full track
- Both tracks are verified by the phase QA run, not issue by issue

Lifecycle

1. Pick the next phase and its open issues from the backlog
2. If an issue does not yet follow `_docs/task-template.md`, the PM grooms
   it. Related issues are groomed together in one PM run
3. The engineer, or the orchestrator on the light track, implements each
   issue in the phase, one at a time, and the full test suite passes
4. When every issue in the phase is implemented, QA runs once and checks
   every acceptance criterion of every issue in the phase
5. On FAIL, the failing issues go back to step 3 with the QA comments as
   input; QA then re-checks only the criteria that failed
6. On PASS for every issue, open the phase PR
7. Repeat until the backlog is empty

Rules

- Step 2 is skipped only when the issue already follows the template and
  its criteria still match the situation. If they no longer match, the PM
  re-grooms it
- The engineer does not close the issue
- QA does not fix the code, only outputs PASS or FAIL
- QA runs once per phase, not once per issue. It checks each criterion
  against the phase diff and runs the tests once for the whole phase. It
  does not repeat checks the brief lists as already done, and does not
  clone repositories or fetch web pages unless a criterion needs it
- QA posts one verdict comment on each issue in the phase
- The phase PR is opened only after every issue has a QA PASS
- Slow setup, such as downloading a tool, is done once before launching
  subagents, not inside each one

Branch, PR and merge

1. The PM grooms the issue so it follows `_docs/task-template.md`, or it
   already does
2. Each phase gets one branch, created from an up-to-date `main` when its
   first issue starts, named `phase-<number>-<short-description>`, for
   example `phase-2-walking-skeleton`. Issues do not get their own branches
3. Commit on that branch, regularly, with clear messages. Each issue ends
   in at least one commit whose message has a `Refs #<issue number>` line
4. When the phase QA run has passed every issue, open one PR into `main`
   that links each issue with a `Closes #<issue number>` line. QA does not
   run again on the PR; CI does
5. Review the PR
6. A human merges the PR, only after every acceptance criterion is checked.
   Agents never merge
7. The issues close when the PR that closes them is merged

`main` is protected by a GitHub ruleset: changes land only through a pull
request, the CI check "Lint, type check and test" must pass before merging,
and force-pushes and deleting `main` are blocked. No second reviewer is
required, so the owner can merge a passing PR.

Tracker

- Project board: TODO - link added once the board is created
