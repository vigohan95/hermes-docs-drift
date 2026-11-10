# Round 3: requests that are not renames. Plan, written before any session was run

Written and committed on 2026-11-10 before the first session of this round. Nothing below
this line was changed after the runs started; results are in `README.md` next to this file.

## The question

Round 2 (`../README.md`) found no difference: asked to rename a flag, `glm-5.3` searched for
the old name, found it in the docs and updated them, with and without the plugin. A rename is
the one request where searching for the old string leads straight to the docs. This round
asks whether there is any other kind of request where the docs end up different with the
plugin installed. The answer is not known. "No difference anywhere" is a possible result and
will be reported as such.

## Requests

Each prompt is the plain request. None mentions documentation. They are in `demo/tasks.py`.

| Task | Prompt | Project |
| --- | --- | --- |
| `default` | `Make notesync retry 5 times by default instead of 3.` | `examples/notesync-tasks` |
| `remove-flag` | `Remove the deprecated --legacy-sync flag.` | `examples/notesync-tasks` |
| `add-flag` | `Add a --dry-run flag that prints what would be copied.` | `examples/notesync-tasks` |
| `remove-env` | `Drop support for the NOTESYNC_TOKEN_FILE environment variable.` | `examples/notesync-tasks` |
| `add-env` | `Let the timeout be set with a NOTESYNC_TIMEOUT environment variable.` | `examples/notesync-tasks` |
| `rename` | `Rename the --output-dir flag of notesync to --dest.` (the round 2 request) | `examples/notesync` |

`examples/notesync-tasks` was written for this round. It is a second small project whose
docs are in three files (README.md, docs/configuration.md, docs/troubleshooting.md). The
default of `--retries` is stated in a table row and in three sentences of prose; the flag
`--legacy-sync` in a table row, a sentence and a command; `NOTESYNC_TOKEN_FILE` in two files.
It was not changed after this plan was committed.

## Arms

- **plugin**: a Hermes home with docs-drift installed from the commit that contains this
  plan, default settings.
- **no plugin**: a Hermes home without it.

Same prompt, same starting tree (a fresh copy of the example with one commit), same Hermes
(`b7db40d`), `-t file`, `--max-requests 16`, `--max-turns 20` for both. Within a task the
sessions alternate: plugin, no plugin, plugin, ... Five sessions per arm.

## How a session is scored

By `demo/tasks.py` (`judge`), which reads the files the session left and nothing else. It
does not use the scanner and does not know which arm it is looking at. It has unit tests
(`tests/test_tasks.py`).

| Task | The docs count as consistent when |
| --- | --- |
| `default` | no doc line that is about retrying (matches `retr` or `tried again`) still contains `3` or `three` as a word |
| `remove-flag`, `remove-env` | no doc line contains the removed name, except a line that says it is gone (`removed`, `no longer`, `dropped`, `not supported`, `unsupported`, `was deleted`) |
| `add-flag`, `add-env` | at least one doc file contains the new name |
| `rename` | no doc line contains `--output-dir` |

A changelog or release-notes file is never counted, on either side. If the requested change
is not in the code at all, the session is scored `not done in the code`, which is neither
consistent nor stale. A session that runs into the request limit, or in which Hermes exits
with an error, is scored on the tree it left and is marked in the table.

Known before the runs and not counted: `docs/troubleshooting.md` also says "four attempts in
total", which follows from 3 retries. The rule for `default` does not look at it.

## What is recorded besides the outcome

From the relay's trace of the conversation (`demo/relay.py --trace`), per session:

- whether the plugin told the model anything: a `docs_drift` entry with new findings or added
  names in an edit result that the model was then sent, or the reminder before the end of the
  turn;
- how many edits of doc files the model issued before the first request that carried such a
  message, and how many in answer to it or later. "The model had already fixed the docs" and
  "the model fixed them after it was told" are different results and are reported separately.

## What the plugin says on these requests, measured without a model

`tests/test_tasks.py` applies the smallest code-only edit for each request and records what
the hooks say:

- `default`: one finding, the table row. The three prose sentences are not reported; no check
  reads a default out of prose. So a model that fixes the table and nothing else will hear
  nothing more from the plugin while the rule above still counts three stale lines.
- `remove-flag`: one finding (docs/troubleshooting.md). The README table row that calls the
  flag deprecated is not reported.
- `remove-env`: two findings, but only once the name is gone from the code entirely; while a
  docstring still names the variable the plugin says nothing.
- `add-flag`, `add-env`: one note each, from the edit-time "names an edit added" report that
  was added in this round (commit `4bb337d`). Before that commit the hooks said nothing here.

## Models

- `glm-5.3`, as in round 2.
- A second, smaller model. `GET /v1/models` on the same endpoint lists 12 models with tool
  calling. Chosen before any run, by size and price as the listing states them:
  `qwen3.8-27b` (27B parameters by its name, input price a fifth of `glm-5.3`). If its first
  two sessions end without a single tool call reaching Hermes, it is recorded as unable to
  drive Hermes, the transcripts are kept, and `glm-5.3-flash` (same family as `glm-5.3`, the
  lowest price tier) is used instead. If that fails the same way, the round has no second
  model and says so.

## Order and budget

At most 350 chat requests in this round, counted by the relay. Order:

1. `glm-5.3`: `add-flag`, then `default`, then `remove-flag`. Three tasks, two arms, five
   sessions each: 30 sessions.
2. Second model: the task from step 1 with the largest difference in consistent sessions
   between the arms; on a tie the one with the most stale sessions without the plugin; on a
   further tie `add-flag`. Two arms, five sessions each.
3. Second model: `rename`. Two arms, five sessions each.
4. `glm-5.3`: `add-env` and `remove-env`.
5. One request on a real repository from the benchmark set. The repository, the prompt and
   the rule are added to this directory in a separate file and committed before its first
   session.

A step that is a task (two arms, five sessions each) is started only if the requests left
cover ten sessions at the average number of requests per session seen so far in this round;
otherwise it is dropped whole and listed as not run. A task is stopped early only if Hermes
itself fails (two sessions in a row that end with an error before any tool call). If the
budget is raised while the round is running, the order stays the same.

No session is run to try things out. The driver was checked end to end against the scripted
stub (`demo/scripted_model.py`), which costs nothing. Every session that reaches the model is
kept and counted, including the ones that go against the plugin. If the driver itself breaks
(not Hermes, not the model), the transcript is kept, marked, and the session is repeated.

## Files

`<model>-<task>-<arm>-<n>.txt`, arm `plugin` or `none`, exactly as `demo/run_real.py --task`
printed it. `python benchmarks/summarize_real.py evidence/real-model/round3` prints the tables
from the `SUMMARY:` line at the end of each file.
