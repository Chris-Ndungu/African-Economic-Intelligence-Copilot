- Tasks are GitHub issues, one at a time
- Read the acceptance criteria before starting and before closing
- Commit regularly

Roles

- PM - grooms a task before anyone implements it, follows _docs/team/pm.md
- Engineer - implements one groomed task, follows _docs/team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows _docs/team/qa-engineer.md

Orchestrator

The main session is the orchestrator. It launches the PM, the engineer
and QA as subagents. It does not groom, implement or test itself.

Lifecycle

1. Pick the next open issue from the backlog
2. PM grooms it
3. Engineer implements it
4. QA verifies it
5. On FAIL, back to step 3 with the QA comment as input
6. On PASS, close the issue
7. Repeat until the backlog is empty

Rules

- Do not skip step 2
- The engineer does not close the issue
- QA does not fix the code, only outputs PASS or FAIL
- The orchestrator closes the issue only after QA outputs PASS

Branch, PR and merge

1. The PM grooms the issue so it follows `_docs/task-template.md`
2. Create a branch from an up-to-date `main`, named `<issue number>-<short-description>`,
   for example `4-project-skills`
3. Commit on that branch, regularly, with clear messages
4. Open a PR into `main` that links the issue with a `Closes #<issue number>` line
5. Review the PR: QA checks every acceptance criterion in the issue
6. A human merges the PR, only after every acceptance criterion is checked.
   Agents never merge
7. The issue closes when the PR that closes it is merged

Tracker

- Project board: TODO - link added once the board is created
