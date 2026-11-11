# Changelog

## 0.1.1 (2026-11-11)

Changes asked for in the review of the catalog entry, and what turned up while making them.
They are about a repository written to attack the machine that scans it. What the checks
report on the measured repositories is the same as before: all 36 were scanned again with
this version, and the findings, file counts and withheld counts equal the stored scans of the
final run and of round 4 (`evidence/rescan.txt`); the four injection runs behind the recall
table were repeated and give the same 817 rows (`evidence/reinject.txt`).

Git:

- Every git child gets `-c core.fsmonitor=false`, `-c core.hooksPath=` the null device and
  `-c core.untrackedCache=false`, so a program named in the repository's config is not
  started.
- The filter drivers named in the config are set to empty before `status` and `diff`: git
  runs a file's clean filter when it has to hash the file. If the drivers cannot be listed
  or named in a `-c` option, those two commands are not run.
- `diff` runs with `--no-textconv` and `--no-ext-diff`, `status` and `diff` with
  `--ignore-submodules=all`, and every `protocol.<name>.allow` is `never`.
- The text of a file at a revision is read with `git cat-file blob`, no longer with
  `git show`. For a path that is a submodule at that revision `git show` prints a commit,
  and with `log.showSignature` in the config it starts the program named in `gpg.program`.
- The files that differ from a revision other than `HEAD` come from `git status` and
  `git diff --cached --name-only REV`, no longer from `git diff --name-only REV`, which
  rewrote `.git/index` even with `GIT_OPTIONAL_LOCKS=0`. A revision that starts with `-` is
  refused.
- The environment of a git child is `PATH`, `HOME`, `LANG`, `LC_ALL` (on Windows also
  `SYSTEMROOT`, `TEMP`, `TMP`, `USERPROFILE`) and `GIT_OPTIONAL_LOCKS=0`,
  `GIT_TERMINAL_PROMPT=0`, `GIT_NO_LAZY_FETCH=1`, `GIT_ALLOW_PROTOCOL=:`, `GIT_WORK_TREE`
  and `GIT_CEILING_DIRECTORIES`. An inherited `GIT_DIR` no longer reaches git, and
  `core.worktree` in the repository's config no longer moves git to another directory.

Files:

- A symbolic link or junction is followed only when its target is inside the repository,
  outside `.git`, and not a name that is never read (`.env`, key files, credential stores).
  The rule is the same for reading a file, for asking whether it exists and for its
  modification time, and for files below a linked directory.
- `.git/config` is read only when it is a regular file in a `.git` directory that is not a
  link.
- Nothing in a `.git` directory is read through a path or a link: not at any depth, not in
  another letter case, and for the repository's own `.git` not under any name that leads to
  the same directory.
- For a file with a name that is never read, only its existence is asked, no longer its
  size and modification time.
- A name from git's listing is used only when it is a plain relative path. On Windows the
  spellings that open another file (`name:stream`, a trailing dot or space, device names,
  short names) are refused or resolved first, and the files Git for Windows lists behind a
  junction are dropped. Without git, the directory walk does not enter a linked directory.

Time:

- One call of a hook has one limit, `hook_time_budget_s`. It now also covers the wait for
  another scan and the git children, and it is checked between doc files inside a check.
  Before, each scan in a call had its own budget and git could add 20 seconds per child.
- Eleven regular expressions that needed quadratic or cubic time on one crafted line or
  file are replaced: code spans, headings, link targets, HTML `src`/`href`, documented
  defaults, V4A patch headers, `cd` in shell blocks, the text before a default, table
  separators, TOML section keys and `.gitmodules` paths. Code spans are now found by a
  one-pass scanner that `tests/test_hardening.py` compares with the old pattern.
- `benchmarks/regex_timing.py` times every pattern in the source on long repetitive input;
  its output for this version is `evidence/regex-timing.txt`.
- Every path is now resolved before it is read, which costs time on a repository with many
  files: on the machine the evidence comes from, with the files in the cache, a scan of
  prettier/prettier took 3.5 to 4.1 seconds before and 4.3 to 5.2 now. Scanning all 36
  measured repositories one after another took 36.2 to 40.8 seconds before and 37.1 to
  43.1 now (three runs each, taken in turns, on a machine that was doing other work).

Scripts: `benchmarks/compare_scans.py` scans the measured repositories again and compares
with `evidence/scans`; `benchmarks/compare_injected.py` does the same for a repeated
injection run.

Tests: 263 to 301.

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
