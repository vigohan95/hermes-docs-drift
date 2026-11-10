# Sessions with a real model

Every file here is the output of `demo/run_real.py` exactly as it was printed (paths under
the temp directory and the Hermes home are replaced as they are printed, by `demo/scrub.py`).
All sessions ran on 2026-11-10 with Hermes at commit `b7db40d` and docs-drift at commit
`4a1d964` (the scanner code is the same as at `aacd813`).

## Model

`glm-5.3` on Vultr Serverless Inference (`https://api.vultrinference.com/v1`, OpenAI-compatible).
`GET /v1/models` listed 33 models, 12 of them marked as supporting tool calling. `glm-5.3` was
tried first because the listing describes it as trained for coding and long agentic work and
it is in the highest price tier. Tool calling worked with Hermes' tool schema in
the first session, so no other model was tried.

## The plan, written down before the counted runs

- Prompt, the same in every run, with no mention of documentation:
  `Rename the --output-dir flag of notesync to --dest.`
- Project: a fresh copy of `examples/notesync` with one commit, for every run.
- Three Hermes homes that differ only in the plugin: installed with default settings;
  installed with `report_after_edit: false` (the plugin says nothing after an edit and only
  reminds before the end of the turn); not installed.
- `-t file` in every run (file tools only), to keep the number of requests down.
- The outcome of a run is decided by a rule that does not involve the plugin: after the
  session, does any doc file other than a changelog still contain `--output-dir`.
- Five runs per configuration. A fourth configuration, a second set of five without the
  plugin, was stopped after its first run because it is the same configuration as the other
  runs without the plugin and the request limit would not have covered it. That one run is
  counted with the runs without the plugin, which makes six.

## Result

| Configuration | Runs | Docs consistent with the code afterwards | Runs in which the plugin told the model something |
| --- | --- | --- | --- |
| Plugin, default settings | 5 | 5 | 5 (the `docs_drift` entry in the result of the code edit) |
| Plugin, reminder only | 5 | 5 | 0 (nothing was open at the end of the turn, so no reminder) |
| No plugin | 6 | 6 | n/a |

**There is no difference in the outcome.** On this task this model searches for the old name
first, finds it in the docs, and updates the docs whether or not the plugin is there.

What the five runs with default settings do show is the mechanism working with a real model:
the code edit came back with a `docs_drift` entry listing the two stale places (README.md:8
and 16, docs/configuration.md:7 and 10), the model went on to edit those files, and the
results of those edits carried `resolved` and, at the end, `still_open: 0`. In runs 1, 3 and
4 the model edited only code first and turned to the docs in the request after it had read
the entry (run 3 says "Docs still reference the old flag — updating them."). In run 2 it
edited the docs in the same request as the second code edit, and in run 5 it had already
started on the README in the same batch as the first code edit.

The reminder before the end of the turn (`pre_verify`) was never delivered by a real-model
session, because no session ended with drift open. That path is shown only by the scripted
run in `../demo-forget.txt` and by the unit tests.

| File | Started (UTC) | Chat requests | Edit results with a `docs_drift` entry | Findings in them | Reminder | Outcome | Turn |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `rename-with-plugin-1.txt` | 12:25:45 | 9 | 2 | 2 | not delivered | docs consistent | 53.6 s |
| `rename-with-plugin-2.txt` | 12:33:30 | 9 | 3 | 2 | not delivered | docs consistent | 57.8 s |
| `rename-with-plugin-3.txt` | 12:36:37 | 5 | 3 | 2 | not delivered | docs consistent | 42.2 s |
| `rename-with-plugin-4.txt` | 12:39:23 | 7 | 3 | 2 | not delivered | docs consistent | 56.6 s |
| `rename-with-plugin-5.txt` | 12:42:35 | 9 | 3 | 2 | not delivered | docs consistent | 53.4 s |
| `rename-reminder-only-1.txt` | 12:28:42 | 7 | 0 | 0 | not delivered | docs consistent | 71.7 s |
| `rename-reminder-only-2.txt` | 12:35:37 | 6 | 0 | 0 | not delivered | docs consistent | 47.4 s |
| `rename-reminder-only-3.txt` | 12:38:26 | 8 | 0 | 0 | not delivered | docs consistent | 45.9 s |
| `rename-reminder-only-4.txt` | 12:41:28 | 11 | 0 | 0 | not delivered | docs consistent | 54.5 s |
| `rename-reminder-only-5.txt` | 12:44:25 | 10 | 0 | 0 | not delivered | docs consistent | 58.6 s |
| `rename-without-plugin-1.txt` | 12:26:51 | 7 | 0 | 0 | n/a | docs consistent | 81.6 s |
| `rename-without-plugin-2.txt` | 12:34:40 | 6 | 0 | 0 | n/a | docs consistent | 46.8 s |
| `rename-without-plugin-3.txt` | 12:37:31 | 7 | 0 | 0 | n/a | docs consistent | 44.7 s |
| `rename-without-plugin-4.txt` | 12:40:32 | 7 | 0 | 0 | n/a | docs consistent | 45.5 s |
| `rename-without-plugin-5.txt` | 12:43:40 | 4 | 0 | 0 | n/a | docs consistent | 35.6 s |
| `rename-without-plugin-6.txt` | 12:31:28 | 7 | 0 | 0 | n/a | docs consistent | 49.8 s |

The header of `rename-reminder-only-*.txt` and of `rename-without-plugin-6.txt` calls the run
"forget": that was the working name of the second scenario. The prompt is the same.

## A real repository

`real-repo-simonw-llm.txt`: simonw/llm at commit `39d3254`, plugin with default settings,
prompt `Rename the LLM_RAISE_ERRORS environment variable to LLM_DEBUG_ERRORS.` The model
searched, read the four places, and sent four patches in one request: the two code files,
the docs page (heading, anchor and text) and the README link. After that batch nothing was
stale, so the plugin added nothing, which is the correct behaviour. 9 chat requests, docs
consistent, the old name left only in `docs/changelog.md`, where it belongs.

`real-repo-code-only-rename.txt` is the same rename applied to the two code files only, with
`sed` and no model, followed by `python -m docsdrift . --since HEAD`: 2 findings (README.md:321;
docs/plugins/advanced-model-plugins.md:743, also 747 and 750). This is what the plugin would
have put into the edit result had the session left the docs alone.

## Two extra sessions, not part of the table

These were decided after the results above were known, to see whether a different plain
request would leave the docs behind. Prompt: `Change the default --timeout of notesync to 60
seconds.` (the README table states the default 30). Outcome rule: does the README still have
the table row with `30` for `--timeout`.

| File | Configuration | Chat requests | Reminder | Outcome |
| --- | --- | --- | --- | --- |
| `extra-default-without-plugin.txt` | no plugin | 4 | n/a | docs consistent |
| `extra-default-reminder-only.txt` | plugin, reminder only | 7 | not delivered | docs consistent |

In both the model changed the code and the README table in the same request.

## Requests

148 chat requests were sent to the model in total: 9 in a first trial session with Hermes'
default toolsets (not kept here: it was made with an earlier transcript format), 119 in the
16 counted sessions, 9 in the real-repository session, 11 in the two extra sessions.

## Running it yourself

```sh
export DOCS_DRIFT_BASE_URL=https://api.vultrinference.com/v1    # any OpenAI-compatible endpoint
export DOCS_DRIFT_MODEL=glm-5.3
export DOCS_DRIFT_API_KEY=...                                    # read from the environment only
HERMES_HOME=<a Hermes home with or without the plugin> python demo/run_real.py --toolsets file
```

Without `DOCS_DRIFT_API_KEY` the script prints `skipped: ...` and exits 0. The key is given
only to `demo/relay.py`, a local relay that adds it to the outgoing request; Hermes is started
with a placeholder key, so the real one cannot appear in Hermes' output or session files.
Every transcript here was also compared against the key value by a script before it was
committed.
