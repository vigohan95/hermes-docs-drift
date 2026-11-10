# Round 3: requests that are not renames. Results

90 sessions on 2026-11-10 between 14:33 and 15:38 UTC. Every `.txt` file here is the output
of `demo/run_real.py --task` exactly as it was printed (paths under the temp directory and
the Hermes home are replaced as they are printed, by `demo/scrub.py`). Hermes was at commit
`b7db40d`. In the sessions with the plugin, docs-drift was installed from commit `c07bd2d`,
the commit that contains [PLAN.md](PLAN.md).

The plan was committed before the first session and has not been changed since. What was
decided while the round was running (a larger budget, a different order, the second batch of
`add-flag`, the request on a real repository) is in [PLAN-ADDENDUM.md](PLAN-ADDENDUM.md).
The second batch of `add-flag` and the request on a real repository were each written down
there and committed before their first session. The decision to run two streams was not:
see [How the round ran](#how-the-round-ran).

Every prompt is a plain change request that does not mention documentation. Every session
starts from a fresh copy of the project. Afterwards `demo/tasks.py` reads the files the
session left and decides the outcome by the rule in the plan. It does not use the scanner
and does not know which arm it is looking at.

## Result

"Consistent" means the rule for that request holds in the tree the session left: the new
name is in at least one doc file, or no doc line still has the old name or value.

| Model | Request | Project | With the plugin: docs consistent / sessions | Without the plugin: docs consistent / sessions | Sessions with the plugin in which it told the model something |
| --- | --- | --- | --- | --- | --- |
| `glm-5.3` | add a flag, first batch (sessions 1-5) | example | 5 / 5 | 2 / 5 | 5 |
| `glm-5.3` | add a flag, second batch (sessions 6-10) | example | 5 / 5 | 0 / 5 | 4 |
| `glm-5.3` | add a flag, the two batches together | example | 10 / 10 | 2 / 10 | 9 |
| `glm-5.3` | add a flag | encode/uvicorn | 5 / 5 | 1 / 5 | 5 |
| `glm-5.3` | add an environment variable | example | 5 / 5 | 5 / 5 | 5 |
| `glm-5.3` | change a default | example | 5 / 5 | 5 / 5 | 2 |
| `glm-5.3` | remove a flag | example | 5 / 5 | 5 / 5 | 4 |
| `glm-5.3` | remove an environment variable | example | 5 / 5 | 5 / 5 | 2 |
| `qwen3.8-27b` | add a flag | example | 5 / 5 | 5 / 5 | 5 |
| `qwen3.8-27b` | rename a flag (the round 2 request) | example | 5 / 5 | 5 / 5 | 5 |

No session ended with the requested change missing from the code. No session ran into the
request limit or Hermes' turn limit, and Hermes exited with status 0 in all 90.

**The arms differ for one kind of request and one model: `glm-5.3` asked to add a flag.**
On the example project the new flag was documented in 10 of 10 sessions with the plugin and
in 2 of 10 without it (first batch 5 of 5 against 2 of 5, second batch 5 of 5 against 0 of
5). In encode/uvicorn it was 5 of 5 against 1 of 5.

**Everywhere else the outcome was the same in both arms.** In all 60 sessions of the other
rows the docs were consistent afterwards, 30 with the plugin and 30 without it. Those rows
are not evidence that the plugin makes an agent fix docs it would otherwise have left.

## The sessions where the arms differ

`glm-5.3` asked for `--dry-run` in the example project reads the code, adds the flag and
stops. In 8 of the 10 sessions without the plugin no doc file mentions `--dry-run`
afterwards. In the other 2 (`none-2`, `none-5`) it read `README.md` on its own and added a
row to the table of flags.

With the plugin, the result of the edit that added the flag carried this, in 9 of the 10
sessions (copied from `glm-5.3-add-flag-plugin-1.txt`, lines wrapped here):

    "note": "This edit added 1 name(s) that no doc mentions. Document them where their
             siblings are documented before finishing, unless they are meant to stay
             undocumented.",
    "problem": "This session's edits added `--dry-run` (notesync/cli.py:18); no doc
                mentions it. README.md documents `--legacy-sync` and 3 other flag(s) of
                the project.",

In all 9 the model had edited no doc file of the project before that and edited one after
it. In the tenth (`plugin-9`) it read `README.md` first and patched the code and the README
in the same answer, so there was nothing for the plugin to say.

In encode/uvicorn the request was `Add a --quiet flag that sets the log level to warning.`
The options are declared in `uvicorn/main.py` and documented one by one in
`docs/settings.md`. With the plugin, all 5 sessions got the note naming `docs/settings.md`
after the first code edit, had not touched a doc file before, and then added a line for
`--quiet` there. Without it, 1 session of 5 (`none-1`) found `docs/settings.md` by itself and
added the line; the other 4 changed `uvicorn/main.py` (one of them also `tests/test_cli.py`)
and stopped.

For scale, Fisher's exact test (two-sided) on each of these tables: first batch 0.17, second
batch 0.008, the two batches together 0.0007, uvicorn 0.048. The first batch alone could
easily have been chance, which is why the second was run.

## Where the arms do not differ

- **`qwen3.8-27b`, add a flag: 5 of 5 and 5 of 5.** This is the same request and project as
  above. Without the plugin this model read `README.md` before its first edit in all 5
  sessions and added the table row itself. (`glm-5.3` read the README before its first edit
  in 1 of its 10 sessions without the plugin.) With the plugin the note arrived before the
  model's doc edit in all 5 sessions, but the other arm shows the model would have made that
  edit anyway. So the difference above belongs to how `glm-5.3` works, not to the request.
- **`glm-5.3`, change a default: 5 of 5 and 5 of 5.** Without the plugin the model's first
  step in all 5 sessions was a search for `retries` or `retry`, which lists the doc lines
  that state the number, and it changed all of them. The plugin told the model something in
  2 of its 5 sessions (4 and 5, where the model edited the code first and the docs after the
  plugin's entry); in the other 3 no doc line was stale when the code edit was checked.
- **`glm-5.3`, remove a flag: 5 of 5 and 5 of 5.** Without the plugin the first step in all
  5 sessions was a search for `legacy-sync`. The plugin told the model something in 4 of 5
  sessions. In 3 of them every doc edit came after that; in 1 the model had already
  edited the docs; in 1 the plugin had nothing to say.
- **`glm-5.3`, add an environment variable: 5 of 5 and 5 of 5.** The request names an option
  that already exists (`--timeout`). Without the plugin the model's first step in all 5
  sessions was a search for `timeout`, which lists the doc lines about that option, and it
  then documented `NOTESYNC_TIMEOUT` in 3 or 4 doc edits per session. With the plugin the
  note about the undocumented variable came with the code edit in all 5 sessions, before
  any doc edit, but the other arm shows the model would have documented it anyway.
- **`glm-5.3`, remove an environment variable: 5 of 5 and 5 of 5.** Without the plugin the
  first step in all 5 sessions was a search for the variable's name. The plugin told the model
  something in 2 of 5 sessions, and in both the model had already edited one of the two doc
  files. In the other 3 the model patched the code and both doc files in one answer and
  there was nothing to report.
- **`qwen3.8-27b`, rename a flag: 5 of 5 and 5 of 5**, as with `glm-5.3` in round 2. The
  plugin's entry reached the model in all 5 sessions; in 2 the doc edits came only after it,
  in 3 the model had edited the docs before.
- **The reminder before the end of a turn (`pre_verify`) was delivered in none of the 45
  sessions with the plugin.** No session reached the end of its turn with a finding or an
  added name still open. As in round 2, that path is shown only by the scripted run in
  `../../demo-forget.txt` and by unit tests.

## What to keep in mind when reading the numbers

- The note about an added name did not exist before this round. It was written (commit
  `4bb337d`) after round 2 had shown no difference, when it was clear that the plugin said
  nothing at all on a request that only adds something, and before any session here. The
  sessions measure the plugin with that note; nothing in round 2 did.
- The example project `examples/notesync-tasks` was written for this round by the author of
  the plugin. encode/uvicorn is the only real repository, with one request, and it is one of
  the 24 repositories the scanner's rules were tuned on (the note about added names was not
  written against it).
- The second batch of `add-flag` was decided after the first had been seen. That is written
  in the addendum, which was committed before the second batch started. Same prompt, tree,
  rule and installed plugin.
- Five sessions per arm per row, two models from one provider, one afternoon.
- The rule for "add" only asks whether some doc file contains the new name. It does not
  judge whether what the model wrote about it is right or in a sensible place.
- `add-env` is not as pure an addition as `add-flag`: its prompt names the existing option
  `--timeout`, and a search for that word leads to the docs. A new variable unrelated to
  anything already documented was not tried.
- "Told the model something" counts what the plugin added to the result of an edit without
  being asked. In 15 of the 45 sessions with the plugin the model also called the plugin's
  `docs_drift_scan` tool by itself. In none of the 15 did a doc edit follow that call.
- In one of the uvicorn sessions with the plugin, the plugin told the model that the note
  was resolved when it was not. See "One wrong message from the plugin" at the end.

## How the round ran

Two streams ran at the same time, each with its own pair of Hermes homes, so no two sessions
shared a home. Within a request the sessions alternate: plugin, no plugin.

| Stream | Hermes homes | Requests, in the order they ran |
| --- | --- | --- |
| A | plugin from `c07bd2d`; no plugin | `glm-5.3` add-flag 1-5, default, remove-flag; `qwen3.8-27b` add-flag; `glm-5.3` add-env |
| B | plugin from `c07bd2d`; no plugin | `qwen3.8-27b` rename; `glm-5.3` add-flag 6-10, uvicorn-add-flag, remove-env |

The second stream started at 14:41 UTC. The part of the addendum that describes the two
streams was committed at 14:51, ten minutes later, while the second model's `rename`
sessions were running on it.

Against the plan and the addendum: the second model's `rename` (step 3) ran before its
`add-flag` (step 2), because step 2 has to wait for step 1 and the second stream was free;
and the second batch of `add-flag` ran before the request on uvicorn, not after it, because
the addendum for uvicorn was still being written when the stream was free. Every step of the
plan was run. Nothing was dropped and no session was repeated.

The line `source:` in a transcript is the commit of the checkout the driver ran from, which
moved as transcripts and the addendum were committed. The plugin installed in the two plugin
homes stayed at `c07bd2d` for all 45 sessions. The transcripts do not print that commit
(the line `plugin:` only says whether Hermes had the plugin); it was read from the two homes
before the first session and again after the last.

Chat requests, counted by the relay: **777 in the 90 sessions**. The limit set for the
round was 350, raised to 600 and then to 850 while it ran (see the addendum). No request
was sent to the model outside these sessions. Round 2 used 148, so both rounds together
used 925.

Each transcript was searched by a script for the value of the API key before it was
committed. None contains it.

## Per request and arm

Printed by `python benchmarks/summarize_real.py evidence/real-model/round3`.

| Model | Task | Arm | Sessions | Docs consistent | Docs stale | Not done in the code | Sessions with an edit of the project's docs | Plugin told the model something | of those: every doc edit came after it | Chat requests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glm-5.3 | add-env | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 5 | 5 | 50 |
| glm-5.3 | add-env | no plugin | 5 (1-5) | 5 | 0 | 0 | 5 | n/a | n/a | 43 |
| glm-5.3 | add-flag | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 5 | 5 | 45 |
| glm-5.3 | add-flag | no plugin | 5 (1-5) | 2 | 3 | 0 | 2 | n/a | n/a | 33 |
| glm-5.3 | add-flag | plugin | 5 (6-10) | 5 | 0 | 0 | 5 | 4 | 4 | 41 |
| glm-5.3 | add-flag | no plugin | 5 (6-10) | 0 | 5 | 0 | 0 | n/a | n/a | 34 |
| glm-5.3 | add-flag | plugin | 10 (all) | 10 | 0 | 0 | 10 | 9 | 9 | 86 |
| glm-5.3 | add-flag | no plugin | 10 (all) | 2 | 8 | 0 | 2 | n/a | n/a | 67 |
| glm-5.3 | default | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 2 | 2 | 35 |
| glm-5.3 | default | no plugin | 5 (1-5) | 5 | 0 | 0 | 5 | n/a | n/a | 25 |
| glm-5.3 | remove-env | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 2 | 0 | 40 |
| glm-5.3 | remove-env | no plugin | 5 (1-5) | 5 | 0 | 0 | 5 | n/a | n/a | 30 |
| glm-5.3 | remove-flag | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 4 | 3 | 51 |
| glm-5.3 | remove-flag | no plugin | 5 (1-5) | 5 | 0 | 0 | 5 | n/a | n/a | 41 |
| glm-5.3 | uvicorn-add-flag | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 5 | 5 | 67 |
| glm-5.3 | uvicorn-add-flag | no plugin | 5 (1-5) | 1 | 4 | 0 | 1 | n/a | n/a | 59 |
| qwen3.8-27b | add-flag | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 5 | 5 | 53 |
| qwen3.8-27b | add-flag | no plugin | 5 (1-5) | 5 | 0 | 0 | 5 | n/a | n/a | 44 |
| qwen3.8-27b | rename | plugin | 5 (1-5) | 5 | 0 | 0 | 5 | 5 | 2 | 50 |
| qwen3.8-27b | rename | no plugin | 5 (1-5) | 5 | 0 | 0 | 5 | n/a | n/a | 36 |

"Sessions with an edit of the project's docs" counts sessions in which the model issued at
least one `write_file` or `patch` on a doc file inside the project. "Every doc edit came
after it" counts the sessions in which the plugin told the model something and the model had
edited no doc file of the project before that request.

## Per session

| File | Started (UTC) | Chat requests | Hermes exit | Plugin told the model | Edits of the project's docs before / after that | Reminder | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `glm-5.3-add-env-none-1.txt` | 15:26:05 | 10 | 0 | n/a | 3 / - | n/a | docs consistent |
| `glm-5.3-add-env-none-2.txt` | 15:29:20 | 8 | 0 | n/a | 3 / - | n/a | docs consistent |
| `glm-5.3-add-env-none-3.txt` | 15:31:40 | 9 | 0 | n/a | 4 / - | n/a | docs consistent |
| `glm-5.3-add-env-none-4.txt` | 15:34:04 | 9 | 0 | n/a | 3 / - | n/a | docs consistent |
| `glm-5.3-add-env-none-5.txt` | 15:36:37 | 7 | 0 | n/a | 3 / - | n/a | docs consistent |
| `glm-5.3-add-env-plugin-1.txt` | 15:24:20 | 13 | 0 | edit result | 0 / 3 | not delivered | docs consistent |
| `glm-5.3-add-env-plugin-2.txt` | 15:27:20 | 8 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-add-env-plugin-3.txt` | 15:30:30 | 10 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-add-env-plugin-4.txt` | 15:32:53 | 8 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-add-env-plugin-5.txt` | 15:35:22 | 11 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-add-flag-none-1.txt` | 14:34:55 | 7 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-10.txt` | 15:04:09 | 7 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-2.txt` | 14:39:45 | 7 | 0 | n/a | 1 / - | n/a | docs consistent |
| `glm-5.3-add-flag-none-3.txt` | 14:43:34 | 6 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-4.txt` | 14:46:20 | 6 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-5.txt` | 14:48:48 | 7 | 0 | n/a | 1 / - | n/a | docs consistent |
| `glm-5.3-add-flag-none-6.txt` | 14:55:23 | 7 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-7.txt` | 14:57:38 | 6 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-8.txt` | 14:59:50 | 7 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-none-9.txt` | 15:01:47 | 7 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-add-flag-plugin-1.txt` | 14:33:49 | 8 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-10.txt` | 15:02:52 | 9 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-2.txt` | 14:36:11 | 8 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-3.txt` | 14:41:37 | 8 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-4.txt` | 14:44:32 | 11 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-5.txt` | 14:47:25 | 10 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-6.txt` | 14:54:10 | 9 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-7.txt` | 14:56:24 | 9 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-8.txt` | 14:58:38 | 9 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-add-flag-plugin-9.txt` | 15:01:00 | 5 | 0 | nothing | 1 / - | not delivered | docs consistent |
| `glm-5.3-default-none-1.txt` | 14:50:33 | 4 | 0 | n/a | 4 / - | n/a | docs consistent |
| `glm-5.3-default-none-2.txt` | 14:53:06 | 4 | 0 | n/a | 4 / - | n/a | docs consistent |
| `glm-5.3-default-none-3.txt` | 14:54:44 | 4 | 0 | n/a | 4 / - | n/a | docs consistent |
| `glm-5.3-default-none-4.txt` | 14:56:43 | 6 | 0 | n/a | 5 / - | n/a | docs consistent |
| `glm-5.3-default-none-5.txt` | 14:58:40 | 7 | 0 | n/a | 4 / - | n/a | docs consistent |
| `glm-5.3-default-plugin-1.txt` | 14:49:50 | 4 | 0 | nothing | 4 / - | not delivered | docs consistent |
| `glm-5.3-default-plugin-2.txt` | 14:51:25 | 11 | 0 | nothing | 5 / - | not delivered | docs consistent |
| `glm-5.3-default-plugin-3.txt` | 14:53:55 | 5 | 0 | nothing | 5 / - | not delivered | docs consistent |
| `glm-5.3-default-plugin-4.txt` | 14:55:31 | 10 | 0 | edit result | 0 / 4 | not delivered | docs consistent |
| `glm-5.3-default-plugin-5.txt` | 14:57:47 | 5 | 0 | edit result | 0 / 5 | not delivered | docs consistent |
| `glm-5.3-remove-env-none-1.txt` | 15:22:08 | 7 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-env-none-2.txt` | 15:24:36 | 6 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-env-none-3.txt` | 15:26:53 | 5 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-env-none-4.txt` | 15:28:31 | 6 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-env-none-5.txt` | 15:30:11 | 6 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-env-plugin-1.txt` | 15:21:09 | 6 | 0 | edit result | 1 / 1 | not delivered | docs consistent |
| `glm-5.3-remove-env-plugin-2.txt` | 15:23:36 | 8 | 0 | nothing | 2 / - | not delivered | docs consistent |
| `glm-5.3-remove-env-plugin-3.txt` | 15:25:37 | 12 | 0 | edit result | 1 / 1 | not delivered | docs consistent |
| `glm-5.3-remove-env-plugin-4.txt` | 15:27:39 | 7 | 0 | nothing | 2 / - | not delivered | docs consistent |
| `glm-5.3-remove-env-plugin-5.txt` | 15:29:18 | 7 | 0 | nothing | 2 / - | not delivered | docs consistent |
| `glm-5.3-remove-flag-none-1.txt` | 15:00:59 | 8 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-flag-none-2.txt` | 15:03:11 | 9 | 0 | n/a | 3 / - | n/a | docs consistent |
| `glm-5.3-remove-flag-none-3.txt` | 15:05:51 | 9 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-flag-none-4.txt` | 15:08:20 | 8 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-flag-none-5.txt` | 15:10:38 | 7 | 0 | n/a | 2 / - | n/a | docs consistent |
| `glm-5.3-remove-flag-plugin-1.txt` | 14:59:40 | 10 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-remove-flag-plugin-2.txt` | 15:02:00 | 9 | 0 | nothing | 2 / - | not delivered | docs consistent |
| `glm-5.3-remove-flag-plugin-3.txt` | 15:04:30 | 13 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-remove-flag-plugin-4.txt` | 15:07:01 | 11 | 0 | edit result | 0 / 2 | not delivered | docs consistent |
| `glm-5.3-remove-flag-plugin-5.txt` | 15:09:24 | 8 | 0 | edit result | 2 / 0 | not delivered | docs consistent |
| `glm-5.3-uvicorn-add-flag-none-1.txt` | 15:06:38 | 10 | 0 | n/a | 1 / - | n/a | docs consistent |
| `glm-5.3-uvicorn-add-flag-none-2.txt` | 15:09:24 | 11 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-uvicorn-add-flag-none-3.txt` | 15:12:31 | 13 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-uvicorn-add-flag-none-4.txt` | 15:16:01 | 11 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-uvicorn-add-flag-none-5.txt` | 15:19:14 | 14 | 0 | n/a | 0 / - | n/a | docs stale |
| `glm-5.3-uvicorn-add-flag-plugin-1.txt` | 15:05:12 | 11 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-uvicorn-add-flag-plugin-2.txt` | 15:07:54 | 13 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-uvicorn-add-flag-plugin-3.txt` | 15:11:02 | 14 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-uvicorn-add-flag-plugin-4.txt` | 15:14:14 | 15 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `glm-5.3-uvicorn-add-flag-plugin-5.txt` | 15:17:35 | 14 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `qwen3.8-27b-add-flag-none-1.txt` | 15:13:11 | 9 | 0 | n/a | 1 / - | n/a | docs consistent |
| `qwen3.8-27b-add-flag-none-2.txt` | 15:15:38 | 8 | 0 | n/a | 1 / - | n/a | docs consistent |
| `qwen3.8-27b-add-flag-none-3.txt` | 15:18:10 | 9 | 0 | n/a | 1 / - | n/a | docs consistent |
| `qwen3.8-27b-add-flag-none-4.txt` | 15:20:28 | 9 | 0 | n/a | 1 / - | n/a | docs consistent |
| `qwen3.8-27b-add-flag-none-5.txt` | 15:23:06 | 9 | 0 | n/a | 1 / - | n/a | docs consistent |
| `qwen3.8-27b-add-flag-plugin-1.txt` | 15:12:03 | 10 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `qwen3.8-27b-add-flag-plugin-2.txt` | 15:14:22 | 10 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `qwen3.8-27b-add-flag-plugin-3.txt` | 15:16:42 | 13 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `qwen3.8-27b-add-flag-plugin-4.txt` | 15:19:14 | 10 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `qwen3.8-27b-add-flag-plugin-5.txt` | 15:21:45 | 10 | 0 | edit result | 0 / 1 | not delivered | docs consistent |
| `qwen3.8-27b-rename-none-1.txt` | 14:42:39 | 6 | 0 | n/a | 4 / - | n/a | docs consistent |
| `qwen3.8-27b-rename-none-2.txt` | 14:45:28 | 8 | 0 | n/a | 4 / - | n/a | docs consistent |
| `qwen3.8-27b-rename-none-3.txt` | 14:48:17 | 9 | 0 | n/a | 4 / - | n/a | docs consistent |
| `qwen3.8-27b-rename-none-4.txt` | 14:50:52 | 6 | 0 | n/a | 4 / - | n/a | docs consistent |
| `qwen3.8-27b-rename-none-5.txt` | 14:52:53 | 7 | 0 | n/a | 3 / - | n/a | docs consistent |
| `qwen3.8-27b-rename-plugin-1.txt` | 14:41:11 | 10 | 0 | edit result | 0 / 3 | not delivered | docs consistent |
| `qwen3.8-27b-rename-plugin-2.txt` | 14:43:54 | 12 | 0 | edit result | 0 / 4 | not delivered | docs consistent |
| `qwen3.8-27b-rename-plugin-3.txt` | 14:46:43 | 13 | 0 | edit result | 4 / 0 | not delivered | docs consistent |
| `qwen3.8-27b-rename-plugin-4.txt` | 14:49:34 | 9 | 0 | edit result | 3 / 0 | not delivered | docs consistent |
| `qwen3.8-27b-rename-plugin-5.txt` | 14:51:58 | 6 | 0 | edit result | 4 / 0 | not delivered | docs consistent |

## A flaw in one recorded count, and its correction

The `SUMMARY:` line of each transcript counts edits of doc files before and after the
plugin first told the model something. The driver that wrote these transcripts counted
every `write_file` or `patch` whose path has a doc suffix, also outside the project. In two
sessions the model wrote scratch notes named `a.md` and `b.md` into a cache directory to
try its change:

- `glm-5.3-add-flag-none-4.txt`: the line says 2 before; none of the 2 was in the project.
- `glm-5.3-add-flag-plugin-4.txt`: the line says 0 before, 3 after; 1 of the 3 was in the
  project.

The transcripts are left as they were printed. `benchmarks/summarize_real.py` counts the
edits again from the tool calls printed in each transcript and keeps only those inside the
project; the tables above use that count, and the script lists the sessions where the two
differ. The outcome of a session never depended on this count: the rule reads the project's
files. The driver was corrected after the last session of the round
(`demo/tasks.py`, `ordering(..., root=...)`).

Two more things a reader of the transcripts will come across. The header of each one says
`edits of doc files the model issued`, which is the uncorrected count. And three transcripts
contain a fragment of a path outside the project that the model itself wrote in a shell
command or that Hermes clipped (`~\AppData\Local\Te ...`, `$LOCALAPPDATA/Temp/...`,
`C:\User ...`); none of them contains a user name.

## One wrong message from the plugin

`glm-5.3-uvicorn-add-flag-plugin-1.txt`. The plugin had told the model that `--quiet` was
documented nowhere (15:05:52Z). The model's patch at 15:06:04Z broke the indentation of
`uvicorn/main.py`, and the plugin added to the result of that patch
`1 docs-drift finding(s) resolved by this edit; 0 still open.` That was false: the file no
longer parsed, the plugin read no flag from it, and so it took the flag for gone. The model
repaired the file at 15:06:10Z, the plugin reported the undocumented flag again, and the
model documented it at 15:06:27Z. The session counts as consistent, and as one where the
plugin spoke and the doc edit came after it. Had the model stopped after the false message,
the plugin would have been the reason for a stale doc.

This is the only one of the 45 sessions with the plugin in which a "resolved" message
follows an edit of a file that is not a doc file. It was found by reading the transcript
after the round. The plugin was changed afterwards (commit `9723303`): a Python file that
does not parse keeps the flags that were read from it when it last did, as long as their
names are still written in it. That change is covered by unit tests only
(`tests/test_added.py`); no session here ran with it.
