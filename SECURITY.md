# Security

## What the plugin does on a machine

The same list as "What it runs and reads" in the [README](README.md):

- It runs `git` in the repository being checked, with five read-only subcommands
  (`ls-files`, `status`, `show`, `diff --name-only`, `check-ignore`) and
  `GIT_OPTIONAL_LOCKS=0`. It runs no other program.
- It reads text files in that repository and `.git/config`. It does not open `.env` files,
  key files or credential stores; the list of skipped names is in `docsdrift/repo.py`.
- It writes nothing to disk, makes no network request and sends no telemetry.
- It has no dependencies outside the Python standard library, no binaries and no code that
  updates itself.

## Text from the repository reaches the model

A finding quotes one line of a doc file and one line of code, each cut at 180 characters,
and puts them in the result of the `write_file` or `patch` call. `docs_drift_explain` adds a
few lines around each when the agent asks for them. Those lines come from the repository
being edited, so a repository written to mislead an agent can place words there. The agent
can read the same lines with its own file tools, and the plugin adds text from nowhere else,
but the quotes are not filtered.

The plugin cannot approve a tool call, run a slash command or answer a confirmation prompt.
The reminder before the end of a turn is sent at most once per turn.

## Reporting a problem

Use "Report a vulnerability" on the Security tab of
<https://github.com/vigohan95/hermes-docs-drift> for anything that should not be public yet.
For everything else, open an issue. Fixes go to `main`; there are no maintained older
versions.
