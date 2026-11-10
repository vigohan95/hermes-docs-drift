# docs-drift

A plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent). When the agent
edits code, it checks whether the README and the other Markdown docs still describe that
code, and puts any new mismatch into the result of the edit, with file and line on both
sides. The agent reads it in the same turn and fixes the docs before it finishes.

It parses files and runs `git`. There is no model call, no network access and no API key.

```text
[11:19:19Z] tool call    patch {"mode": "replace", "path": "notesync/cli.py", "old_string": "\"--output-dir\"", "new_string": "\"--dest\""}
[11:19:22Z] tool result  patch (3328 ms)
             (fields from Hermes' own tool, not shown: diff, files_modified, lint, resolved_path, success)
             "docs_drift": {
               "note": "This edit left 2 place(s) where the docs no longer match the code. Update the docs (or the code) before finishing; docs_drift_explain <id> shows both sides.",
               "new": [
                 {
                   "id": "DD-5fb3c36f",
                   "check": "cli-flag-undefined",
                   "confidence": "high",
                   "doc": "README.md:8",
                   "doc_quote": "notesync ./notes --output-dir ./backup",
                   "problem": "`--output-dir` was removed from the code by the edit, but the docs still use it.",
                   "code": "notesync/cli.py:12",
                   "code_quote": "parser.add_argument(\"--dest\", default=\"./out\", help=\"where the copies go\")",
                   "suggestion": "The same edit added `--dest` (notesync/cli.py:12). If this is a rename, replace `--output-dir` with `--dest` in the docs.",
                   "also_at_lines": [
                     16
                   ]
                 },
   (cut here: the second finding, docs/configuration.md:7, has the same shape)
               ],
               "still_open": 2
             }
```

That is the start of a recorded Hermes session ([evidence/demo-rename.txt](evidence/demo-rename.txt)).
In that session the model side is a fixed script, not a language model; see
[The demo](#the-demo) for what that does and does not show.

## Install

```sh
hermes plugins install vigohan95/hermes-docs-drift --enable
```

Needs Hermes 0.21.6 or later. No Python packages are installed: the plugin uses the
standard library only. `git` should be on `PATH`; without it the plugin walks the directory
and cannot compare with an earlier state.

Hermes defers plugin tools behind its `tool_search` and `tool_call` tools by default, so the
model finds `docs_drift_scan` by searching for it. The hooks do not depend on that: they run
whenever the plugin is enabled.

## What it adds to a session

**Hooks (automatic).**

| Hook | When | What it does |
| --- | --- | --- |
| `pre_tool_call` | before the first `write_file` or `patch` in a repository | Scans the repository once and keeps the result as the session's baseline. |
| `transform_tool_result` | after each `write_file` or `patch` that succeeded | Scans again. If the edit caused drift that was not in the baseline, adds a `docs_drift` entry to the tool result. Adds nothing otherwise, except a short note when an edit resolves drift it reported earlier. |
| `pre_verify` | when the agent is about to finish a turn in which it changed files | If drift from this session is still open, asks the agent once to continue, and lists it. |

A finding that was already there before the session started is never reported by the hooks.

**Tools (the model calls them).**

- `docs_drift_scan` scans a repository. Arguments: `path`, `changed_only` (only drift caused
  by uncommitted changes, compared with `git HEAD`), `checks`, `min_confidence`,
  `max_findings`.
- `docs_drift_explain` takes a `finding_id` and returns the doc lines, the code lines, the
  reasons the finding was reported and a suggested fix.

**Slash command (you type it).**

```text
/drift [path]            scan the repository (default: the working directory)
/drift --changed [path]  only drift introduced by uncommitted changes
/drift --all [path]      also run the opt-in checks
/drift explain <id>      show one finding with both sides
/drift checks            list the checks
```

**Command line (no Hermes needed).** From a checkout of this repository:

```text
$ python -m docsdrift /path/to/project --since HEAD
docs-drift (new since HEAD): 2 findings (2 doc files checked against 4 code files, 109 ms)

README.md:8  cli-flag-undefined  [high]  DD-5fb3c36f
  `--output-dir` was removed from the code by the edit, but the docs still use it.
  docs: README.md:8  notesync ./notes --output-dir ./backup
  code: notesync/cli.py:12  parser.add_argument("--dest", default="./out", help="where the copies go")
  also at lines: 16
  fix:  The same edit added `--dest` (notesync/cli.py:12). If this is a rename, replace `--output-dir` with `--dest` in the docs.
...
```

The exit status is 1 when there are findings, so it can be used in CI. Other options:
`--json`, `--checks`, `--min-confidence`, `--max-findings`, `--explain`, `--list-checks`,
`--no-git`, `--exit-zero`.

## Checks

| Check | Default | Reports |
| --- | --- | --- |
| `path-missing` | on | A Markdown link or image points at a file that is not in the repository. |
| `cli-flag-undefined` | on | Docs show a command-line flag that the code no longer defines. |
| `env-undefined` | on | Docs name an environment variable that nothing in the code reads. |
| `default-mismatch` | on | Docs state a default value that differs from the default in the code. |
| `npm-script-missing` | on | Docs tell the reader to run a `package.json` script that does not exist. |
| `make-target-missing` | on | Docs tell the reader to run a make target that no Makefile defines. |
| `path-ref-missing` | opt-in | A file path written in inline code does not exist in the repository. |
| `cli-flag-undocumented` | opt-in | The code defines a flag that the docs listing its siblings do not mention. |
| `env-undocumented` | opt-in | The code reads an environment variable that the docs listing its siblings do not mention. |

The three opt-in checks are off because they were wrong too often on real repositories (see
[Measured precision](#measured-precision)). Turn them on with `/drift --all` or the `checks`
setting.

What the code side understands:

| Fact | Where it is read from |
| --- | --- |
| Flag definitions with line and default | Python (`argparse`, `click`, `typer`), JavaScript and TypeScript (`commander`, `yargs`), Go (`flag`, `cobra`/`pflag`) |
| Flag names, any language | every `--name` literal in a non-doc file, and identifiers and strings that spell the name |
| Environment variables | read calls in Python, JavaScript, Go, Rust, Ruby and shell with line and default; any `NAME_LIKE_THIS` token in a non-doc file |
| npm scripts | every `package.json` in the repository |
| make targets | every `Makefile`, `makefile`, `GNUmakefile` and `*.mk` |
| Files | `git ls-files`, plus untracked and git-ignored files on disk |

The docs side is Markdown and MDX: links, images, inline code, fenced code blocks, tables
and lists. Changelogs, release notes, migration guides, translated READMEs and vendored
directories are not checked.

## How a finding is decided

There are two kinds of evidence, and they are not equally strong.

**An edit.** The hooks, `changed_only` and `--since` compare the code before and after. If a
flag, variable, script, target or file was defined before, is in no non-doc file now, and
the docs still use it, that is reported with high confidence. When the same edit added one
new name of the same kind, the finding says so and suggests the rename. This is the main
use of the plugin.

**The repository as it stands.** A plain scan has no "before". A flag in the docs that the
code does not define might be another program's flag, a placeholder, or a flag defined in a
way the scanner cannot read. So a plain scan reports only when it is hard to be wrong:

- a flag must be used with this project's own command, or sit in an option list most of
  which the code defines, and its name must not survive anywhere in the code, even as an
  identifier or a string;
- a variable must carry the project's prefix or a prefix the code reads at least two other
  variables with, and the name must be in no non-doc file;
- a default must be stated on a line that names exactly one option, and the code must
  define exactly one static default for it;
- a link must be relative, stay inside the repository, and its target must be neither
  tracked, on disk, git-ignored nor inside a submodule.

Everything that fails one of these tests is counted, not reported. The count is in the
output as `not_reported` with the reason, for example `flag-has-loose-trace: 2`.

The cost is recall. A plain scan of a repository where a flag was renamed last month, and
whose old name still appears in a variable somewhere, says nothing. The numbers below show
how much is lost.

## Measured precision

Method: 24 open-source repositories, each cloned and pinned to a commit
([evidence/targets.txt](evidence/targets.txt)), scanned with all nine checks. Every finding
was read by hand against both files at that commit and labelled true or false with a
one-line reason ([evidence/labels.json](evidence/labels.json)). "True" means a reader who
follows the doc line is misled about the code. Anything arguable is labelled false.

The repositories were used in three sets of eight. The tuning set was scanned while the
checks were being written. The other two were each scanned for the first time with a fixed
commit of the scanner, and that first run is the only unseen one for that set.

| Run | Scanner commit | Set | Seen before? | Default checks: found / true | Opt-in checks: found / true |
| --- | --- | --- | --- | --- | --- |
| round 1 | `974f7f2` | tuning | yes | 0 / 0 | 5 / 1 |
| round 1 | `974f7f2` | held-out 1 | **no** | 4 / 0 | 4 / 0 |
| round 2 | `806d448` | tuning | yes | 0 / 0 | 5 / 1 |
| round 2 | `806d448` | held-out 1 | yes | 0 / 0 | 0 / 0 |
| round 2 | `806d448` | held-out 2 | **no** | 5 / 1 | 9 / 1 |
| round 3 | `8ff4f2c` | all 24 | yes | 1 / 1 | 14 / 2 |
| final | `b7ba05d` | all 24 | yes | 1 / 1 | 14 / 2 |

Read plainly:

- On repositories the scanner had not seen, the default checks reported 9 findings and 1 of
  them was true; the opt-in checks reported 13 and 1 was true. That is the only estimate of
  precision on a new repository that these runs give, and it is poor.
- After each unseen run the false reports were traced to their cause and the checks were
  changed. Round 1: flags of other programs on the same command line (`pip`'s `--pre`),
  placeholders (`--LONG`), flags passed to a user's own script. Round 2: a bug that stopped
  asking git about ignored files after 40 links (3 of the 4 false reports), and a sentence
  about a future default. Each cause has a test in `tests/test_precision_guards.py`.
- With those changes the default checks report 1 finding, which is true, across the 24
  repositories (795 Markdown files). No unseen set is left, so this number says the known causes are fixed. It
  does not say what the next repository will show.
- The one true default finding is in junegunn/fzf: `README.md:776` names
  `FZF_EXPANSION_OPS`, the code reads `FZF_EXPANSION_OPTS`.
- The opt-in checks were right 2 times in 14 in the final run (psf/black: `blackd` defines
  `--bind-host` and no doc mentions it; pdm-project/pdm: the installer reads `PDM_REPO`).
  The usual cause of the false ones is documentation that is generated at build time and is
  not in the repository, so "the docs do not mention it" is wrong.

The table is printed by `benchmarks/precision.py` ([evidence/precision.txt](evidence/precision.txt)).
The script fails if a finding has no label. The scan results it reads are in
`evidence/scans/`.

Well-kept projects have little drift for a plain scan to find, which is why the counts are
small. To measure the edit case, drift was injected.

### Injected drift

`benchmarks/inject.py` changes the code in memory and leaves the docs alone: it renames a
flag (as a string, and again as a refactoring that also renames the identifiers), renames an
environment variable, renames an npm script or a make target, or removes a linked file. The
candidates are chosen with a fixed seed from names that both the code and the docs contain,
without asking the scanner. A mutation counts as detected when the scan of the changed tree
has a finding of the matching check with that name and the scan of the original tree did
not.

| Run | Scanner commit | Set | Injected | Detected, edit-aware | Detected, plain scan |
| --- | --- | --- | --- | --- | --- |
| round 1 | `974f7f2` | tuning | 248 | 238 (96.0%) | 166 (66.9%) |
| round 1 | `974f7f2` | held-out 1, unseen | 165 | 122 (73.9%) | 79 (47.9%) |
| round 2 | `806d448` | held-out 2, unseen | 121 | 118 (97.5%) | 54 (44.6%) |
| final | `b7ba05d` | tuning | 248 | 238 (96.0%) | 81 (32.7%) |
| final | `b7ba05d` | held-out 1 | 165 | 147 (89.1%) | 47 (28.5%) |
| final | `b7ba05d` | held-out 2 | 121 | 118 (97.5%) | 54 (44.6%) |
| final | `b7ba05d` | all 24 | 534 | 503 (94.2%) | 182 (34.1%) |

All runs are in [evidence/recall.txt](evidence/recall.txt).

"Edit-aware" is what the hooks and `changed_only` do. "Plain scan" is a whole-repository
scan of the changed tree with no knowledge of the edit. The gap between the two columns is
the recall given up for precision, as described above. The plain-scan column fell between
round 1 and round 2 on the tuning set (166 to 81) because the rules added after the first
unseen run stop a plain scan from reporting a flag whose name still appears anywhere in the
code.

In the final run no injection produced a finding about an unrelated item, with one
exception that is correct: removing the Makefile of nektos/act made 10 `make` commands in
its docs point at targets that no longer exist.

The misses are listed by `python benchmarks/summarize_inject.py <dir> --misses`.

### The Hermes repository itself

After the 24, the scanner was run on Hermes Agent at commit `b7db40d` (1,180 Markdown
files, 21,805 other files). It is a hard case: a monorepo that ships documentation for many
third-party tools as skills.

The first run (scanner `8ff4f2c`) gave 147 findings from the default checks. 109 of them
were links inside two pages that had been exported from another documentation site, whose
links were never relative to this tree (`optional-skills/mlops/training/unsloth/references/`). Five rules were added after reading that run
(commit `b7ba05d`), so Hermes is a 25th tuning repository, not a test.

The run after that gives 33 findings from the default checks. All 33 were labelled by hand
([evidence/hermes-self/labels.json](evidence/hermes-self/labels.json)):

- 5 are true. `apps/desktop/BUILDING.md` (lines 149, 353, 394, 399) and
  `scripts/build/README.md` (line 5) link to `../../docs/<page>.md`. The repository has no
  `docs/` directory at its root; the pages are in `website/docs/developer-guide/`.
- 18 are false and come from pages that document another tool's command line (comfy-cli,
  hyperframes, darwinian-evolver, page-agent) inside `optional-skills/` and their copies
  under `website/docs/user-guide/skills/`. The scanner compared them with Hermes' own code.
- 3 are links in a skill page that are written relative to the skill's root directory, not
  to the page. Arguable; labelled false.
- 6 concern options or variables of plugins and programs that live in other repositories
  (`--skill-conflict`, `--oss-llm`, `BUZZ_ACP_RELAY_OBSERVER`). They cannot be decided from
  this repository; labelled false.
- 1 misreads a sentence about `--toolsets` as a statement of its default.

So on this repository the default checks were right 5 times in 33. The 138 findings of the
opt-in checks in the same scan were not labelled. `ignore_paths` is the setting for leaving
directories such as `optional-skills/` out.

## Speed

Measured on one Windows 11 machine, Python 3.11, single runs.

| What | Time |
| --- | --- |
| First scan in a process, each of the 24 repositories, files already in the OS file cache (final run) | 0.1 to 3.2 s |
| The largest of them, prettier/prettier (9,218 non-doc files): first scan / rescan | 3.2 s / 0.7 s |
| Rescan of each of the other 23 with the in-memory cache | 0.3 s or less |
| First scan right after cloning, files not in the OS file cache (round 1: 16 of the repositories, an earlier commit of the scanner) | 0.8 to 89.7 s; prettier 89.7 s, vitejs/vite 24.7 s, yt-dlp 14.8 s |
| Hermes Agent (21,805 non-doc files): first scan / rescan | 52.2 s / 3.9 s |
| `docs_drift_scan` with `changed_only` on the example project, inside Hermes | 193 and 184 ms (two runs) |
| `docs_drift_explain`, inside Hermes | 37 ms |
| Hermes' `patch` tool on the example project, plugin not installed: first edit / later edits | 3774 ms / 3032 and 2926 ms |
| The same with the plugin's hooks, two runs: first edit / later edits | 3328 and 3542 ms / 2866 to 3067 ms |

The last two rows are one run without the plugin and two with it
([evidence/demo-without-plugin.txt](evidence/demo-without-plugin.txt) and the two demo
transcripts). The first edit with the plugin includes the baseline scan. Hermes' own `patch`
call takes about three seconds on this machine and varies by several hundred milliseconds
from run to run, which is more than the hooks add on a project of this size; these numbers
do not show a cost and do not rule out a small one.

A hook stops scanning when it has used `hook_time_budget_s` (default 8 seconds) and then
adds nothing to the tool result. Files already parsed stay cached, so on a large repository
the first edits of a session may go unchecked and later ones are checked. On a repository
the size of Hermes Agent the first scan does not fit in that budget.

## Settings

Under `plugins.entries.docs-drift` in the Hermes config:

| Setting | Default | Meaning |
| --- | --- | --- |
| `checks` | `[]` | Checks to run. Empty means the defaults. Use ids, `all`, or `+id` / `-id` relative to the defaults. |
| `min_confidence` | `medium` | Lowest confidence to report: `high` or `medium`. |
| `report_after_edit` | `true` | Add the `docs_drift` entry to edit results. |
| `nudge_before_finish` | `true` | Ask the agent to continue once if it finishes while drift it introduced is open. |
| `hook_time_budget_s` | `8` | Seconds a hook may spend scanning. |
| `max_reported` | `8` | Findings listed in one hook message. |
| `ignore_names` | `[]` | Flag, variable, script or target names never to report. |
| `ignore_paths` | `[]` | Glob patterns of doc files never to report on. |

## What it does not do

- It does not read prose for meaning. "Uploads are retried three times" is not checked
  against anything.
- It does not check function signatures, API endpoints, config-file keys or code samples.
- It reads Markdown and MDX only. reStructuredText, AsciiDoc and docstrings are ignored.
- It does not edit the docs. It reports; the agent or you decide what is right.
- It does not know about documentation that is generated at build time.
- In a monorepo that also ships documentation about other tools, a plain scan reports that
  documentation against the wrong code. Use `ignore_paths`.
- A page on which eight or more relative links are dead, and they are at least half of
  its links, is taken to be written for another tree, and its links are not reported
  (except links to a file the current edit removed). A page of this repository that is
  really that broken is missed.
- A flag that is deprecated but still accepted, or reachable only through an alias the
  scanner cannot see, can be reported as undocumented by the opt-in checks.
- Hooks watch Hermes' `write_file` and `patch` tools. A file changed by a shell command is
  seen at the next edit or by `/drift --changed`, not at once.

## What it runs and reads

- Runs `git ls-files`, `git status`, `git show`, `git diff --name-only` and
  `git check-ignore` in the repository being checked, with `GIT_OPTIONAL_LOCKS=0`. It runs
  no other program.
- Reads text files in that repository and `.git/config` (for the repository name). It never
  opens `.env` files, key files or credential stores; the list is in `docsdrift/repo.py`.
- Writes nothing. The baseline and the cache live in memory for the session.
- Makes no network request and sends no telemetry.

## The demo

`python demo/run_demo.py rename` and `python demo/run_demo.py forget` run a real Hermes
session against a copy of `examples/notesync` and print a transcript. Hermes, its agent
loop, its `patch` tool, plugin loading and the hooks are unmodified. The model is not: the
session talks to `demo/scripted_model.py`, a local stub that returns a fixed list of tool
calls whatever it is sent. The transcripts therefore show that the plugin loads in Hermes,
that the hooks fire and what the agent is given. They do not show how a language model
reacts to it. Recorded runs: [evidence/demo-rename.txt](evidence/demo-rename.txt) and
[evidence/demo-forget.txt](evidence/demo-forget.txt).

## Development

```sh
python -m pytest                      # 172 tests; needs pytest and nothing else
python -m docsdrift . --checks all    # this repository checks its own docs
python benchmarks/run_scans.py <clones_dir> <out_dir> owner__name ...
python benchmarks/precision.py evidence/scans evidence/labels.json
python benchmarks/inject.py <clones_dir> <out_dir> owner__name ...
python benchmarks/summarize_inject.py evidence/injected/final-tuning
```

`<clones_dir>` holds one clone per repository, named `owner__name`, checked out at the
commit in [evidence/targets.txt](evidence/targets.txt). [evidence/README.md](evidence/README.md)
says which file comes from which run.

The output of `hermes plugins validate` is in [evidence/validate.txt](evidence/validate.txt).
The workflow in `.github/workflows/ci.yml` is written to run the tests on three operating
systems and then, on Linux, to validate and install the plugin in a pinned Hermes checkout
and run both demos. It had not run on GitHub when this README was written; everything
reported here was run on one Windows machine.

## License

MIT. See [LICENSE](LICENSE).
