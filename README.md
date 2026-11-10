# docs-drift

A plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent). When the agent
edits code, the plugin checks whether the README and the other Markdown docs still describe
that code: command-line flags, environment variables, stated defaults, npm scripts, make
targets and links to files. If the edit left a doc line behind, the result of that edit says
so, with file and line on both sides, so the agent can fix the docs in the same turn.

It parses files and runs `git`. It makes no model call and no network request and needs no
API key.

```sh
hermes plugins install vigohan95/hermes-docs-drift --enable
```

Needs Hermes 0.21.6 or later. No Python packages are installed.

## Does it change what the agent does? Measured with a real model

106 sessions in real Hermes with a real model, in two sets on 2026-11-10. Each session got
one plain change request that says nothing about documentation, for example
`Add a --dry-run flag that prints what would be copied.` Every request was run with the
plugin installed (default settings) and without it, from the same starting files; nothing
else differed. After each session a script read the files it left and decided whether the
docs still agree with the code: after a rename, a removal or a changed default, no doc line
still has the old name or value; after an addition, some doc file mentions the new name. The
models are `glm-5.3` and the smaller `qwen3.8-27b`, both on Vultr Serverless Inference.

| Model | Request | Project | With the plugin: docs consistent / sessions | Without the plugin: docs consistent / sessions | Sessions with the plugin in which it told the model something |
| --- | --- | --- | --- | --- | --- |
| `glm-5.3` | add a flag, first batch | example | 5 / 5 | 2 / 5 | 5 |
| `glm-5.3` | add a flag, second batch (a replication) | example | 5 / 5 | 0 / 5 | 4 |
| `glm-5.3` | add a flag, both batches together | example | 10 / 10 | 2 / 10 | 9 |
| `glm-5.3` | add a flag | encode/uvicorn | 5 / 5 | 1 / 5 | 5 |
| `glm-5.3` | add an environment variable | example | 5 / 5 | 5 / 5 | 5 |
| `glm-5.3` | change a default | example | 5 / 5 | 5 / 5 | 2 |
| `glm-5.3` | remove a flag | example | 5 / 5 | 5 / 5 | 4 |
| `glm-5.3` | remove an environment variable | example | 5 / 5 | 5 / 5 | 2 |
| `glm-5.3` | rename a flag (first set) | example | 5 / 5 | 6 / 6 | 5 |
| `qwen3.8-27b` | add a flag | example | 5 / 5 | 5 / 5 | 5 |
| `qwen3.8-27b` | rename a flag | example | 5 / 5 | 5 / 5 | 5 |

**The plugin changed the outcome for one kind of request with one of the two models:
`glm-5.3` asked to add a flag.** Without the plugin this model added the flag to the code and
usually stopped there. The new flag ended up in the docs in 2 of 10 sessions on the example
project and in 1 of 5 on encode/uvicorn. With the plugin, the result of the code edit said
that no doc mentions the new flag and where the other flags are documented, and the flag
ended up in the docs in 10 of 10 and 5 of 5 sessions. In 14 of those 15 the model had not
touched a doc file before the plugin's note; in the other one it documented the flag in the
same answer as the code and the plugin had nothing to say.

**For every other request the outcome was the same with and without the plugin**, and so it
was for the second model on both of its requests, the added flag included. In all 20
`glm-5.3` sessions of the second set that ran those requests without the plugin, the first
thing the model did was search the project for the name or value it had been asked about
(`legacy-sync`, `retry`, `timeout`, `NOTESYNC_TOKEN_FILE`); the search showed the doc lines,
and the model updated them itself. Those rows are not evidence that the plugin makes an
agent fix docs it would otherwise have left.

What to keep in mind about the one difference:

- It is one model and one kind of request, in two projects, with 5 sessions per arm and
  batch. `qwen3.8-27b` given the same request on the same project read the README before
  editing and documented the flag itself in 5 of 5 sessions without the plugin.
- The note about an added name was written on the day of the measurement, after the first
  set had shown no difference and before the sessions that measure it. It is the newest and
  least measured part of the plugin; see "Names an edit added" under
  [What it adds to a session](#what-it-adds-to-a-session).
- The example projects were written by the plugin's author. encode/uvicorn is the only real
  repository, with one request, and is one of the 24 repositories the scanner was tuned on.
- The second batch of five per arm was decided after the first had been seen (5 of 5 against
  2 of 5 could have been chance). That decision was committed before the second batch ran,
  and the table gives both batches separately.
- The rule only asks whether a doc file mentions the new flag, not whether what the model
  wrote about it is right.

The first set also ran 5 sessions with the plugin in reminder-only mode
(`report_after_edit: false`) on the rename: 5 of 5 consistent, and the plugin said nothing in
any of them. In no session with the plugin, in either set, was the reminder before the end
of a turn delivered, because no session reached the end of a turn with something still open.

What the plugin is for does not depend on these numbers: the check runs on every edit
whether or not the model thinks of the docs, it is the same check every time, and it costs
no model call. Whether a given model needs it is what the table is about, and for most of
the table the answer was no.

Plans written before the counted sessions, every transcript and the per-session tables:
[the first set](evidence/real-model/README.md) (16 counted sessions and 3 more, 148 chat
requests) and [the second set](evidence/real-model/round3/README.md) (90 sessions, 777 chat
requests).

## Limits, in short

- It checks names and paths, not meaning: flags, environment variables, defaults, npm
  scripts, make targets and links, in Markdown and MDX only.
- The hooks see edits made with Hermes' `write_file` and `patch` tools. A file changed by a
  shell command is seen at the next such edit.
- A rename spread over several edits is reported when the last use of the old name is gone
  from the code, not before.
- A scan of a whole repository with no edit to compare against (`/drift`, or the command line
  without `--since`) is often wrong on a repository it was not tuned on: 15 findings, 2 of
  them true, on 12 repositories it had never seen. The hooks do not work that way; they
  report only what an edit changed.
- The edit-time path was measured on the same 12 repositories with changes made by a
  script (a flag, variable, script or target renamed, a linked file removed; the docs left
  alone): 211 of 221 such changes were reported, and no finding was about anything other
  than the changed item. Of the 131 flag and variable reports, the first doc line of each
  was read: 5 are lines that use the same name for something else (the shell's `PATH`, an
  example in a note). Scripted renames are not the edits a person or a model makes; see
  [Injected drift](#injected-drift).
- Documentation generated when the docs are built (Sphinx directives, embedded `--help`
  output), man pages and reStructuredText are not read.
- The test suite passes in CI on Linux, macOS and Windows with Python 3.11, 3.12 and 3.14,
  and the validator, the install and both scripted example sessions pass in real Hermes on
  Linux in CI. The real-model sessions and the precision and injection measurements were
  run on one Windows machine.

The longer list is under [What it does not do](#what-it-does-not-do).

## What the agent is given

From one of the sessions above
([evidence/real-model/rename-with-plugin-3.txt](evidence/real-model/rename-with-plugin-3.txt)),
as Hermes printed it:

```text
[12:37:07Z] tool call    patch {"new_string": "    parser.add_argument(\"--dest\", default=\"./out\", help=\"where the copies go\")", "old_string": "    parser.add_argument(\"--output-dir\", ...
[12:37:10Z] tool result  patch (2985 ms)
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
   (cut here: a second edit of cli.py)
[12:37:15Z] assistant    Docs still reference the old flag — updating them.
   (cut here: four patch calls on README.md and docs/configuration.md)
[12:37:24Z] tool result  patch (2815 ms)
             (fields from Hermes' own tool, not shown: diff, files_modified, lint, resolved_path, success)
             "docs_drift": {
               "resolved": [
                 "DD-6d2fee65"
               ],
               "still_open": 0,
               "note": "1 docs-drift finding(s) resolved by this edit; 0 still open."
             }
```

The lines marked "cut here" replace parts of the transcript; the first `patch` line is cut at
the right. Nothing else is changed. The model's own search at the start of the session had
already listed the doc lines, so this transcript does not show that the entry is what made
it edit the docs.

## Install

```sh
hermes plugins install vigohan95/hermes-docs-drift --enable
```

Needs Hermes 0.21.6 or later. That is the oldest numbered release, and its source already
has the three hooks and the registration calls used here
([evidence/requires-hermes.txt](evidence/requires-hermes.txt)); the plugin itself was run
only on Hermes `main` at commit `b7db40d` (2026-11-10, after v0.23.1). No Python packages are
installed: the plugin uses the standard library only. `git` should be on `PATH`; without it
the plugin walks the directory and cannot compare with an earlier state.

Hermes defers plugin tools behind its `tool_search` and `tool_call` tools by default, so the
model finds `docs_drift_scan` by searching for it. The hooks do not depend on that: they run
whenever the plugin is enabled.

## What it adds to a session

**Hooks (automatic).**

| Hook | When | What it does |
| --- | --- | --- |
| `pre_tool_call` | before the first `write_file` or `patch` in a repository | Scans the repository once and keeps the result as the session's baseline. |
| `transform_tool_result` | after each `write_file` or `patch` that succeeded | Scans again. If the edit caused drift that was not in the baseline, adds a `docs_drift` entry to the tool result. Adds nothing otherwise, except a short note when an edit resolves drift it reported earlier, and, once per session and repository, a `not_checked` note when an edit could not be checked (for example because the scan ran out of its time budget). |
| `pre_verify` | when the agent is about to finish a turn in which it changed files | If drift from this session is still open, asks the agent once to continue, and lists it. With `report_after_edit: false` this is the only thing the plugin says (reminder-only mode): it scans here by itself. |

A finding that was already there before the session started is never reported by the hooks.

**Names an edit added.** The checks look for docs that say something the code no longer does.
The opposite case, code that gained something the docs do not have yet, is reported by the
hooks only, and only for what the session itself added: when an edit adds a flag definition
or a read of an environment variable, no doc file mentions the new name, and the docs already
document a sibling (another flag of the project; another variable with the same prefix), the
edit result gets an `added` list ("This session's edits added `--dry-run` (cli.py:14); no doc
mentions it"), pointing at the place where the siblings are documented. It stays open, and is
part of the reminder before the turn ends, until a doc mentions the name. It runs inside the
same scan and the same time budget. `report_added: false` turns it off.

This was added on 2026-11-10 after the measurements under "Measured precision" were made. It
is not one of the nine checks and it is not part of any precision or injection number in this
README: `docs_drift_scan` without a session edit, `/drift`, `changed_only` and the command
line never report it. It has unit tests, and it is what the "add a flag" and "add a variable"
rows of the table at the top of this README measure: on an example project written for that
purpose and, for the flag, on encode/uvicorn. How often it is wrong on other real
repositories has not been measured. Two cases where it will be wrong are known: docs
generated from the code at build time (the name is not in any file yet), and a flag that is
meant to stay undocumented but is not marked hidden in the code.

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

Everything that fails one of these tests is counted, not reported. The text output ends
with the count and the reasons, for example `withheld as uncertain: 2 (flag-has-loose-trace: 2).`;
in JSON it is the `not_reported` field.

The cost is recall. A plain scan of a repository where a flag was renamed last month, and
whose old name still appears in a variable somewhere, says nothing. The numbers below show
how much is lost, and how often a plain scan is still wrong.

## Measured precision

This section is about scans of a whole repository with no edit to compare against, which is
the hard case. The hooks do not use it.

Method: 36 open-source repositories, each cloned and pinned to a commit
([evidence/targets.txt](evidence/targets.txt)), scanned with all nine checks. Every finding
was read by hand against both files at that commit and labelled true or false with a
one-line reason ([evidence/labels.json](evidence/labels.json)). "True" means a reader who
follows the doc line is misled about the code. Anything arguable is labelled false.

The repositories were used in four sets. The tuning set (8) was scanned while the checks
were being written. Held-out 1 (8), held-out 2 (8) and held-out 3 (12) were each scanned for
the first time with a fixed commit of the scanner, and that first run is the only unseen one
for that set. The checks were changed after held-out 1 and after held-out 2. They were not
changed after held-out 3.

| Run | Scanner commit | Set | Seen before? | Default checks: found / true | Opt-in checks: found / true |
| --- | --- | --- | --- | --- | --- |
| round 1 | `974f7f2` | tuning | yes | 0 / 0 | 5 / 0 |
| round 1 | `974f7f2` | held-out 1 | **no** | 4 / 0 | 4 / 0 |
| round 2 | `806d448` | tuning | yes | 0 / 0 | 5 / 0 |
| round 2 | `806d448` | held-out 1 | yes | 0 / 0 | 0 / 0 |
| round 2 | `806d448` | held-out 2 | **no** | 5 / 1 | 9 / 1 |
| round 3 | `8ff4f2c` | tuning, held-out 1 and 2 | yes | 1 / 1 | 14 / 1 |
| final | `b7ba05d` | tuning, held-out 1 and 2 | yes | 1 / 1 | 14 / 1 |
| round 4 | `4a1d964` | held-out 3 | **no** | 15 / 2 | 48 / 2 |

The checks at `4a1d964` are the checks of the final run: `docsdrift/checks.py`, `facts.py`
and `docs.py` did not change in between.

Read plainly:

- **The number for a repository the scanner has not seen is the last row: 15 findings from
  the default checks, 2 true; 48 from the opt-in checks, 2 true.** That is the scanner as it
  is shipped, on 12 repositories (501 Markdown files) chosen by a rule that was written down
  before anything was cloned ([evidence/heldout3-rule.md](evidence/heldout3-rule.md), the
  walk through the search result is in
  [evidence/heldout3-selection.txt](evidence/heldout3-selection.txt)). Nothing was tuned
  afterwards.
- Over the three first-time runs together (28 repositories, three versions of the scanner)
  the default checks reported 24 findings and 3 were true; the opt-in checks reported 61 and
  3 were true.
- The "1 / 1" of the final run on the first 24 repositories is a number on repositories the
  rules had been adjusted to. Held-out 3 shows that it did not carry over.
- The 15 default findings of held-out 3 are in 4 of the 12 repositories; 10 of them are in
  one (mvanhorn/cli-printing-press, 226 Markdown files of skills, retrospectives and design
  notes). The 13 false ones, by cause:
  - 5: a shell variable that a bash snippet in the docs sets and reads itself
    (`PP_GO_VERSION_INPUT`, `CLI_SOURCE_ZIP`), reported as an environment variable the
    program does not read;
  - 2: a comment marker in a bash snippet (`# PRINTING_PRESS_SKILL_UPDATE_START`), read as a
    variable name;
  - 2: a dated retrospective or design note that proposes a flag or says a flag is
    deliberately absent;
  - 1: a flag registered with default `0` meaning "not set", while the effective default the
    docs state (50) is applied elsewhere in the code;
  - 1: a link written relative to a skill's root directory, not to the page;
  - 2: links in a source file that is compiled into the program and published under another
    directory, where the links resolve.
- The two true ones: medialab/xan `docs/cookbook/dataviz.md:862` links to `sigmajs.org/`
  without `https://`, so it opens a path inside the repository; CLIUtils/CLI11
  `book/chapters/formatting.md:45` shows an image that is in `book/images/`, not next to the
  page. The true one from held-out 2 is junegunn/fzf `README.md:776`, which names
  `FZF_EXPANSION_OPS` where the code reads `FZF_EXPANSION_OPTS`.
- The opt-in checks were right 2 times in 48 on held-out 3 (alexellis/arkade: the pasted
  help of one command lacks a flag the code registers; cli-printing-press: an instruction
  names `docs/CHANGELOG.md`, the file is at the root). The usual causes of the false ones:
  the page describes files of a program that this repository generates, not of the
  repository (9); a pasted help of one subcommand compared with flags of other subcommands
  (8 in arkade); dated notes; option lists written by a Sphinx directive when the docs are
  built (3 in tmux-python/tmuxp).
- One label was corrected on 2026-11-10. psf/black `--bind-host` (opt-in check, tuning set)
  was labelled true in the first rounds because the page source never spells the flag. The
  page embeds the output of `blackd --help` when the docs are built, so the published page
  does show it. The table above uses the corrected label; before the correction the opt-in
  column read 5 / 1 for the tuning set and 14 / 2 for the 24.

The table is printed by `benchmarks/precision.py` ([evidence/precision.txt](evidence/precision.txt)).
The script fails if a finding has no label. The scan results it reads are in
`evidence/scans/`.

Well-kept projects have little drift for a plain scan to find, which is why the true counts
are small. To measure the edit case, drift was injected.

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
| round 5 | `35e6564` | held-out 3, unseen | 221 | 211 (95.5%) | 83 (37.6%) |

All runs are in [evidence/recall.txt](evidence/recall.txt). The last row was run once, on
the 12 repositories of held-out 3, after everything above it, and nothing in the scanner was
changed because of it. Three of those 12 repositories gave no candidate (no name that both
the code and a checked doc contain), so the 221 come from 9.

"Edit-aware" is what the hooks and `changed_only` do. "Plain scan" is a whole-repository
scan of the changed tree with no knowledge of the edit. The gap between the two columns is
the recall given up for precision, as described above. The plain-scan column fell between
round 1 and round 2 on the tuning set (166 to 81) because the rules added after the first
unseen run stop a plain scan from reporting a flag whose name still appears anywhere in the
code.

In the final run no injection produced a finding about an unrelated item, with one
exception that is correct: removing the Makefile of nektos/act made 10 `make` commands in
its docs point at targets that no longer exist. (Those runs recorded at most ten such
findings per injection, so "10" there may be a cut-off list. The round 5 run records all of
them.)

On held-out 3 the count of findings about an unrelated item is 0 in all 221 injections. The
211 detections came with 455 findings, since a renamed name is usually on several doc lines;
all 455 name the changed item. A finding with the right name is still not always a useful
message. The first doc line of each of the 131 flag and variable detections was read: for
the 93 flag detections every one is the project's own command or flag description; of the
38 variable detections, 5 point at a line that uses the name for something else (`PATH` of
the user's shell three times, a shell test in a skill file, an example error message in a
requirements note). The remaining lines of the 455 were not read. The notes are in
[evidence/injected/round5-heldout3/READING.md](evidence/injected/round5-heldout3/READING.md).

The misses are listed by `python benchmarks/summarize_inject.py <dir> --misses`.

### The Hermes repository itself

After the first 24, the scanner was run on Hermes Agent at commit `b7db40d` (1,180 Markdown
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
| First scan in a process, each of the first 24 repositories, files already in the OS file cache (final run) | 0.1 to 3.2 s |
| The largest of them, prettier/prettier (9,218 non-doc files): first scan / rescan | 3.2 s / 0.7 s |
| Rescan of each of the other 23 with the in-memory cache | 0.3 s or less |
| Held-out 3, 12 repositories: first scan / rescan | 0.4 to 32.4 s / 0.45 s or less |
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

A hook stops scanning when it has used `hook_time_budget_s` (default 8 seconds). The first
time that happens in a session the tool result gets a `not_checked` note saying so; after
that the hook adds nothing. Files already parsed stay cached, so on a large repository
the first edits of a session may go unchecked and later ones are checked. On a repository
the size of Hermes Agent the first scan does not fit in that budget.

## Settings

Under `plugins.entries.docs-drift` in the Hermes config:

| Setting | Default | Meaning |
| --- | --- | --- |
| `checks` | `[]` | Checks to run. Empty means the defaults. Use ids, `all`, or `+id` / `-id` relative to the defaults. |
| `min_confidence` | `medium` | Lowest confidence to report: `high` or `medium`. |
| `report_after_edit` | `true` | Add the `docs_drift` entry to edit results. Set to `false` for reminder-only mode. |
| `nudge_before_finish` | `true` | Ask the agent to continue once if it finishes while drift it introduced is open. |
| `report_added` | `true` | In a session, also say when an edit added a flag or environment variable that no doc mentions (see "Names an edit added"). |
| `hook_time_budget_s` | `8` | Seconds a hook may spend scanning. |
| `max_reported` | `8` | Findings listed in one hook message. |
| `ignore_names` | `[]` | Flag, variable, script or target names never to report. |
| `ignore_paths` | `[]` | Glob patterns of doc files never to report on. |

## What it does not do

- It does not read prose for meaning. "Uploads are retried three times" is not checked
  against anything.
- It does not check function signatures, API endpoints, config-file keys or code samples.
- It reads Markdown and MDX only. reStructuredText, AsciiDoc, man pages and docstrings are
  ignored.
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

### Known weaknesses that were found and not fixed

These were seen in the measurements above, or while preparing them, and left as they are, so that the numbers stay
the numbers of the code that is shipped.

- When a name is removed over several edits, the hooks report it only at the edit after
  which no non-doc file contains it. If one use is left in the code (a test, a comment, a
  string), nothing is reported at all.
- A plain scan does not recognise a variable whose name starts with an underscore
  (zoxide's `_ZO_MAXAGE`) or one that `click` or `typer` binds to an option with `envvar=`
  (llm's `LLM_TOOLS_DEBUG`) as an environment variable of the program. Until 2026-11-10 the
  edit-time path missed them as well: in copies of ajeetdsouza/zoxide and simonw/llm,
  renaming those two names in the code gave no finding. The hooks, `--since` and
  `/drift --changed` now report such a name when an edit takes it out of the code and the
  docs still have it; the same two renames now give `env-undefined` at `README.md:431` and
  at `docs/usage.md:134`. That change was made after every measurement in this README,
  the real-model sessions included, and is covered by unit tests and those two checks only.
  Man pages are still not read as docs.
- A documented default is read in two places only: the `Default` column of a table row, and
  the words "default", "defaults to" or "default is" followed directly by a number, a quoted
  value, a code span or true/false, on a line that names exactly one option. Anything else
  is not compared with the code. That includes the form encode/uvicorn uses,
  `**Default:** *5*` at the end of a list item, where the emphasis marks stand between the
  word and the value: in a clone of uvicorn, changing the default of
  `--timeout-worker-healthcheck` from 5 to 15 in the code gave no finding, although
  `docs/settings.md:79` still says 5.
- Plain scans report variables that a bash snippet in the docs sets for itself, and comment
  markers in such snippets, as environment variables of the program (7 of the 13 false
  default findings on held-out 3).
- Plain scans treat dated retrospectives, decision records and design notes as current
  documentation.
- A flag registered with a placeholder default (`0` meaning "not set")
  is compared with the documented effective default and reported as a mismatch.
- Links written relative to a skill's root directory, and links in a source file that is
  published under another directory, are reported as dead.
- The opt-in checks compare a pasted `--help` of one subcommand with the flags of every
  subcommand, and do not know when a page's option list is written by a Sphinx or MyST
  directive at build time, or when a page describes files of a program that the repository
  generates.
- The reminder before the end of a turn was delivered in no session with a real model, in
  either set, because none reached the end of a turn with drift or an undocumented new
  name still open. It is exercised by the scripted demo and by unit tests only.

## What it runs and reads

- Runs `git ls-files`, `git status`, `git show`, `git diff --name-only` and
  `git check-ignore` in the repository being checked, with `GIT_OPTIONAL_LOCKS=0`. It runs
  no other program.
- Reads text files in that repository and `.git/config` (for the repository name). It never
  opens `.env` files, key files or credential stores; the list is in `docsdrift/repo.py`.
- Writes nothing. The baseline and the cache live in memory for the session.
- Makes no network request and sends no telemetry.

## The demos

There are three drivers. Each runs an unmodified Hermes (agent loop, `patch` tool, plugin
loading, hooks) against a copy of an example project and prints a transcript.

**With a real model: `demo/run_real.py`.** The model is any OpenAI-compatible endpoint with
tool calling, named by three environment variables. The script is not part of the tests or
of CI, because it needs a key and costs money: without `DOCS_DRIFT_API_KEY` it prints one
line starting with `skipped:` and exits with status 0.

```sh
export DOCS_DRIFT_BASE_URL=https://api.vultrinference.com/v1    # any OpenAI-compatible endpoint
export DOCS_DRIFT_MODEL=glm-5.3
export DOCS_DRIFT_API_KEY=...                                    # read from the environment only
HERMES_HOME=<a Hermes home with or without the plugin> python demo/run_real.py --toolsets file
```

The prompt is the plain request and nothing else. Whether the plugin takes part depends only
on the Hermes home in use. The key is given to `demo/relay.py`, a local relay that adds it to
the outgoing request, counts the requests and logs what the model was sent; Hermes is started
with a placeholder key, so the real one cannot appear in Hermes' output or session files.
`--project DIR --prompt TEXT --old NAME` runs another request on another checkout, and
`--max-requests N` stops the relay after N requests.

`--task NAME` runs one of the fixed requests of the measurement at the top of this README:
`rename` on `examples/notesync`; `default`, `remove-flag`, `remove-env`, `add-flag` and
`add-env` on `examples/notesync-tasks`, a second small project with docs in three files; and
`uvicorn-add-flag`, which also needs `--project` with a checkout of encode/uvicorn at commit
`a99c1b7`. The requests and the rule that decides the outcome of each are in `demo/tasks.py`.
After the session the driver reads the files it left, prints `OUTCOME:` and one `SUMMARY:`
line, and `python benchmarks/summarize_real.py <directory>` makes the tables from those
lines.

The recorded sessions of the first set (16 counted, 1 on simonw/llm, 2 extra; 148 chat
requests in all, including a first trial session) are in
[evidence/real-model/](evidence/real-model/README.md), and those of the second set (90
sessions, 777 chat requests) in
[evidence/real-model/round3/](evidence/real-model/round3/README.md). The result table of both
is at the top of this README. In the session on simonw/llm the model
changed the code and the docs in one batch of four patches, so nothing was stale after it
and the plugin added nothing. The same rename applied to the code only, without a model,
gives the 2 findings the plugin would have reported:
[evidence/real-model/real-repo-code-only-rename.txt](evidence/real-model/real-repo-code-only-rename.txt).

**With a scripted model: `demo/run_demo.py rename` and `demo/run_demo.py forget`.** The
session talks to `demo/scripted_model.py`, a local stub that returns a fixed list of tool
calls whatever it is sent. This needs no key and is what CI runs. It shows that the plugin
loads in Hermes, that the hooks fire and what the agent is given; it does not show how a
language model reacts. `forget` is the only place where the reminder before the end of a
turn is delivered: the stub answers "Done" after the code edit, and Hermes' `pre_verify`
hook sends it the list of open findings once. Recorded runs:
[evidence/demo-rename.txt](evidence/demo-rename.txt) and
[evidence/demo-forget.txt](evidence/demo-forget.txt).

**Typed into the interactive chat: `demo/type_drift.py`.** Starts `hermes chat --cli` in a
pseudo-terminal, in a copy of `examples/notesync` in which the flag has been renamed in the
code only, types `/drift` and `/drift --changed` one key at a time, presses Enter and prints
what Hermes printed in answer. No model is contacted; Hermes handles slash commands itself.
It needs the pseudo-terminal package Hermes depends on (pywinpty or ptyprocess), is not run
in CI, and has been run on Windows only. Recorded run:
[evidence/slash-command-typed.txt](evidence/slash-command-typed.txt). An earlier record, in
which the handler Hermes registered for `/drift` was called through Hermes' plugin manager
without a terminal, is [evidence/slash-command.txt](evidence/slash-command.txt).

## Development

```sh
python -m pytest                      # 258 tests; needs pytest and nothing else
python -m docsdrift . --checks all    # this repository checks its own docs
python benchmarks/run_scans.py <clones_dir> <out_dir> owner__name ...
python benchmarks/precision.py evidence/scans evidence/labels.json
python benchmarks/inject.py <clones_dir> <out_dir> owner__name ...
python benchmarks/summarize_inject.py evidence/injected/final-tuning
python benchmarks/summarize_real.py evidence/real-model/round3
```

`<clones_dir>` holds one clone per repository, named `owner__name`, checked out at the
commit in [evidence/targets.txt](evidence/targets.txt). [evidence/README.md](evidence/README.md)
says which file comes from which run.

The output of `hermes plugins validate` is in [evidence/validate.txt](evidence/validate.txt).
The workflow in `.github/workflows/ci.yml` runs the tests on Linux, macOS and Windows with
Python 3.11, 3.12 and 3.14 and then, on Linux, validates and installs the plugin in a pinned
Hermes checkout and runs both scripted demos. It does not run `demo/run_real.py` or
`demo/type_drift.py`. All ten jobs passed on commit `2eb97cd`. The
first run, on `35e6564`, failed in the nine test jobs: pytest imported the entry point under
the name of the checkout directory, which is not a Python identifier there. That is fixed
in `2eb97cd` and `tests/test_layout.py` guards it. The real-model sessions and the precision
and injection measurements were run on one Windows machine and nowhere else.

## License

MIT. See [LICENSE](LICENSE).
