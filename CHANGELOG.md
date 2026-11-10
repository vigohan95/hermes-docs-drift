# Changelog

## 0.1.0 (2026-11-10)

First version.

- Hooks: `pre_tool_call` takes a baseline before the first `write_file` or `patch` in a
  repository; `transform_tool_result` adds a `docs_drift` block to the result of an edit that
  left the docs wrong, or that added a flag or environment variable no doc mentions;
  `pre_verify` reminds the agent once before the turn ends if something is still open.
- Tools: `docs_drift_scan` and `docs_drift_explain`.
- `/drift` in a Hermes chat and `python -m docsdrift` on the command line, with an exit
  status for CI.
- Checks for command-line flags, environment variables, documented defaults, npm scripts,
  make targets and links to files, in Markdown and MDX.
- Measurements published with the code: 106 recorded sessions with two models, with and
  without the plugin; whole-repository precision on 36 open-source repositories, 28 of them
  held out; 221 scripted changes on the 12 repositories of the last held-out set. The numbers
  and their limits are in the [README](README.md).

Each catalog entry pins one commit of this repository. A later commit reaches users only
through a new catalog pull request.
