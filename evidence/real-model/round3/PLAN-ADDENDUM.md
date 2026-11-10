# Round 3: changes to the plan made while the round was running

`PLAN.md` is unchanged since it was committed. Everything that was decided later is in this
file, each part committed before the sessions it is about.

## 1. Written 2026-11-10 14:52 UTC, after the first `add-flag` batch

At this point the 10 sessions of the first `glm-5.3` `add-flag` batch had finished (they are
committed together with this file); `glm-5.3` `default` and `qwen3.8-27b` `rename` were
running.

### Budget and order

The limit of 350 chat requests was set by the person who asked for this round. They raised
it to 600 while the first sessions of step 1 were running, and to 850 after the first
`add-flag` batch, and changed the order of what comes after step 3. The plan said the order
would stay the same if the budget was raised; that sentence no longer holds. The order is
now:

1. steps 1 to 3 as planned;
2. step 5, the request on a real repository (its details are in part 2 of this file, added
   before its first session);
3. the replication described below;
4. step 4 (`glm-5.3`: `add-env`, `remove-env`), which is dropped first if the budget runs
   short.

The rule for dropping a task is the one in the plan, with 850 in place of 350.

### Two streams

To finish in the time available the sessions run in two streams at the same time, each with
its own pair of Hermes homes, so that no two sessions share a home. Both plugin homes have
docs-drift installed from commit `c07bd2d` (the commit that contains the plan) with the same
`config.yaml`; both homes without the plugin have no `config.yaml`. Within a task the
sessions still alternate plugin, no plugin. Running two streams means a later step can start
before an earlier one has finished. It does not change which steps are run, because the
budget covers everything up to the replication at the request counts seen so far.

The transcripts print the commit of the driver's checkout in the line `source:`. That commit
moves when this file and later ones are committed. The plugin installed in the Hermes homes
does not: it stays at `c07bd2d` for every session of the round.

### Replication of `add-flag`, decided after seeing its result

The first batch of `glm-5.3` `add-flag` ended like this:

| Arm | Sessions | Docs consistent | Docs stale |
| --- | --- | --- | --- |
| plugin | 5 | 5 | 0 |
| no plugin | 5 | 2 | 3 |

This is the first difference between the arms in any round, it rests on five sessions per
arm, and the behaviour that produces it (the note about a name an edit added) was written in
this same round. Five against five can come out like this by chance. So the same pair is run
a second time: sessions 6 to 10 of each arm, same model, same prompt, same starting tree,
same rule, same limits, plugin installed from the same commit `c07bd2d`.

The decision to replicate was made after the first batch was seen, not before. The results
will be reported as two separate rows (first batch, replication) and then pooled, with the
number of sessions in every cell. If the replication shows no difference, or the opposite
one, it is reported in the same place and the same way.

### A flaw in what is recorded, found in the first batch

The count "edits of doc files the model issued" counts every `write_file` or `patch` call
whose path ends in `.md`, `.txt` and so on. In two sessions so far
(`glm-5.3-add-flag-none-4`, `glm-5.3-add-flag-plugin-4`) the model wrote scratch notes named
`a.md` and `b.md` into a cache directory outside the project to try its change, and these
were counted. The outcome of a session does not depend on this count: the rule reads the
project's files. The driver is not changed while the round is running. The results will list
every session in which an edit outside the project was counted and give the count without
it, taken from the tool calls printed in the transcript.

## 2. Written 2026-11-10 14:57 UTC, before the first session on a real repository

Step 5 of the plan: one request on a real repository from the benchmark set.

### Repository, request, rule

- Repository: `encode/uvicorn` at commit `a99c1b7`, the checkout the benchmark already uses.
  Each session starts from a fresh local clone of it.
- Request: `Add a --quiet flag that sets the log level to warning.` It does not mention
  documentation. The string `--quiet` occurs in no file of the checkout.
- Rule, the same as for `add-flag`: the docs count as consistent when at least one doc file
  contains `--quiet`. `CHANGELOG.md` and `docs/release-notes.md` are not counted. The session
  counts as done in the code when a file that is not a doc file contains `"--quiet"` or
  `'--quiet'`.
- Task name in `demo/tasks.py`: `uvicorn-add-flag`. Files:
  `glm-5.3-uvicorn-add-flag-<arm>-<n>.txt`.

Why this repository: the command-line options are declared in `uvicorn/main.py`, 667 lines of
`click.option` calls, and documented one by one in `docs/settings.md`. Nothing in `main.py`
names that file, the README mentions three options in passing and lists none, and the
checkout has 20 Markdown files. A session that only follows the code does not come across the place where the option
belongs.

Why an added flag and not another kind of request: this was chosen after the first `add-flag`
batch on the example project (part 1), where the arms differed. A changed default was looked
at before that and ruled out: uvicorn writes defaults as `**Default:** *5*` at the end of a
list item, no check reads that form, so the hooks say nothing and both arms would be the same
by construction. That is a limit of the plugin and is listed as one in the README. No
removal request was tried on this repository.

What is known about this repository beforehand: it is one of the 24 repositories the scanner's
rules were tuned on (whole-repository findings and the injected renames and removals). The
note about an added name was written in this round against the example project, not against
uvicorn.

### What the hooks say on this request, measured without a model

On a fresh clone, one edit that adds a `click.option("--quiet", ...)` to `uvicorn/main.py`
and nothing else, passed through the same hook functions Hermes calls:

    added-flag-undocumented  docs/settings.md:104
    This session's edits added `--quiet` (uvicorn/main.py:370); no doc mentions it.
    docs/settings.md documents `--app-dir` and 48 other flag(s) of the project.
    Document `--quiet` in docs/settings.md (the other flags are around line 104), or leave
    it out on purpose.

and the reminder before the end of the turn repeats it. So with the plugin the model is told
which file documents the flags. Whether it then edits that file, and whether a model without
the plugin finds the file on its own, is what the sessions measure.

### Arms and limits

`glm-5.3`, plugin (installed from `c07bd2d`, default settings) against no plugin, five
sessions per arm, alternating, `-t file`, `--max-turns 20` as in every other task.
`--max-requests` is 24 instead of 16 for both arms: the files are larger than in the example
project, and the relay's limit should not be what ends a session before Hermes' own limit of
20 turns does. A session that runs into either limit is scored on the tree it left and
marked.

### What changed in the driver for this

`demo/run_real.py --task uvicorn-add-flag --project <checkout of encode/uvicorn>` clones the
checkout (line endings as the repository has them, `origin` set to the upstream URL), refuses
to run if the clone is not at `a99c1b7`, and scores the result with the same `judge` function.
Three tests were added to `tests/test_tasks.py`. Nothing under `docsdrift/` changed; the
plugin installed in the Hermes homes is still `c07bd2d`. The changed driver was run once
against the scripted stub (`demo/scripted_model.py`, no model) on the uvicorn checkout before
this was committed.
