# Evidence

Everything here was produced by running the code in this repository on one Windows 11
machine on 2026-11-10. Nothing was edited afterwards except where a file says so. The test
suite and the scripted example sessions also run in CI (Linux, macOS and Windows for the
tests; Linux for Hermes); no file in this directory comes from CI.

## Which run is which

| Name in file paths | Scanner commit | What was scanned |
| --- | --- | --- |
| `round1` | `974f7f2` | tuning set; held-out 1 for the first time |
| `round2` | `806d448` | tuning set and held-out 1 again; held-out 2 for the first time |
| `round3` | `8ff4f2c` | all 24 repositories |
| `final` | `b7ba05d` | all 24 repositories, and Hermes Agent |
| `round4` | `4a1d964` | held-out 3 (12 more repositories), for the first and only time |

Commits after `b7ba05d` change the hooks, the command line, the wording of the report, the
elapsed-time field of change scans, the README and the files in this directory. They do not
change a check (`docsdrift/checks.py`, `facts.py` and `docs.py` are the same files at
`b7ba05d` and at `4a1d964`), so the final run was not repeated, and round 4 measures the same
checks on repositories they had not seen. No check was changed after round 4.

The four sets and the commit each repository was scanned at are in `targets.txt`.

## Files

| File | What it is |
| --- | --- |
| `targets.txt` | The 36 repositories and Hermes Agent, with the commit of each clone. Written by reading `git rev-parse HEAD` in every clone. |
| `scans/<run>-<set>/*.json` | Every finding of a whole-repository scan with all nine checks, one file per repository. Written by `benchmarks/run_scans.py`. `run.log` has the scanner commit and the times. |
| `labels.json` | One hand label (true or false, with the reason) for every distinct finding in `scans/`. |
| `heldout3-rule.md` | The rule by which the 12 repositories of held-out 3 were chosen, written before the search was run. |
| `heldout3-selection.txt` | Output of `benchmarks/select_heldout3.py`: the search result walked in order, with the reason each repository was taken or skipped. The script was run before the `heldout3` lines were added to `targets.txt`. |
| `precision.txt` | Output of `python benchmarks/precision.py evidence/scans evidence/labels.json`. |
| `injected/<run>-<set>/*.json` | Result of every injected change. Written by `benchmarks/inject.py`. |
| `recall.txt` | Output of `benchmarks/summarize_inject.py` for every directory in `injected/`. |
| `hermes-self/round3/hermes-agent.json` | Scan of Hermes Agent with scanner `8ff4f2c`, before the rules that followed from it. |
| `hermes-self/final/hermes-agent.json` | Scan of Hermes Agent with scanner `b7ba05d`. |
| `hermes-self/labels.json` | Hand labels for the 33 default-check findings of that final scan. Its opt-in findings are not labelled. |
| `real-model/` | Round 2: sessions of Hermes with a real model (`glm-5.3` on Vultr Serverless Inference), with and without the plugin, on a rename. Written by `demo/run_real.py`. Its own `README.md` has the plan, the result table and the request count. |
| `real-model/round3/` | Round 3: 90 sessions with and without the plugin on requests that are not renames (add, remove, change a default; one request in encode/uvicorn), and a second model (`qwen3.8-27b`). Written by `demo/run_real.py --task`. One of the 90 transcripts, `qwen3.8-27b-rename-plugin-4.txt`, is kept on the branch `evidence-raw` and has a pointer file here (`qwen3.8-27b-rename-plugin-4.MOVED.md`), because Hermes' install scanner flags one line of it. `PLAN.md` was committed before the first session and `PLAN-ADDENDUM.md` before the sessions each of its parts is about; `README.md` has the results, with the tables printed by `benchmarks/summarize_real.py`. |
| `demo-rename.txt`, `demo-forget.txt` | Output of `python demo/run_demo.py rename` and `forget` against Hermes Agent `b7db40d` with the plugin installed from commit `2071824`. |
| `demo-without-plugin.txt` | The `rename` script run against a Hermes home in which the plugin is not installed. The driver's checks fail, as they should; the file is kept for the timing of Hermes' `patch` tool without the hooks. The line `plugin:` at its top names the source checkout, not an installed copy. |
| `validate.txt` | Output of `hermes plugins validate` for this repository. |
| `requires-hermes.txt` | Why `requires_hermes` is `>=0.21.6`: what the source of each numbered Hermes release contains. A reading of the source at each tag, not a run. |
| `slash-command-typed.txt` | Output of `python demo/type_drift.py`: `/drift` and `/drift --changed` typed into `hermes chat --cli` in a pseudo-terminal, and what Hermes printed in answer. No model was contacted. |
| `slash-command.txt` | Recorded earlier, before `/drift` had been typed in an interactive chat: a short script asked Hermes' plugin manager (`hermes_cli.plugins`) for the handler the plugin registered for `/drift` and called it. The file has the script, quoted at the top, and its output. |

## Things to know when reading the files

- One label was corrected after the final run: psf/black `--bind-host` (opt-in check
  `cli-flag-undocumented`, tuning set) from true to false, because the page embeds the
  output of `blackd --help` when the docs are built. `precision.txt` was printed again with
  the corrected label; the scan files were not touched.
- `slash-command.txt` was recorded before the last line of the text report was reworded. It
  says `not reported (uncertain, N)` where the current code prints
  `withheld as uncertain: N (reason: n, ...)`. The files in `real-model/` have the current
  wording.
- The `run.log` of `scans/round4-heldout3/` was written from the saved scan files after the
  run, because the 12 repositories were scanned in two calls; it says so at its top.
- In the demo transcripts and `slash-command.txt` the temporary directory of the machine they
  were recorded on is written as `%TEMP%`. For the four files recorded before `demo/scrub.py`
  existed, that replacement was made afterwards and is the only edit; the drivers now make it
  while they print. The value after `--api-key` in the stub transcripts is the literal text
  `not-a-real-key`; the model stub ignores it.
- The times in `scans/round1-*/run.log` are first scans right after cloning. The times in
  the later runs were taken with the files already in the operating system's file cache
  and are much lower for that reason.
- The clone of commitizen-tools/commitizen lacks two test fixtures whose file names are too
  long for a default Windows checkout. They are test data, not docs or command-line code.
- In `recall.txt`, "findings after an injection that were about something else" lists 10
  findings in nektos/act after its Makefile was removed. They are correct: the docs run
  `make` targets that no longer exist once the file is gone.
- Up to and including the `final-*` runs, `benchmarks/inject.py` kept only the first ten
  entries of `other_new_findings` per injection, so that "10" may be a cut-off list. The
  cut was removed before `injected/round5-heldout3/` was run; that run records every one,
  and has none.
- `injected/round5-heldout3/` is the injection run on held-out 3: scanner commit `35e6564`,
  run once on 2026-11-10 after all the other runs. `READING.md` in that directory says what
  was read by hand afterwards and what was not.
- The `run.log` files of round 1, and of round 2 for the tuning set and held-out 1, do not
  name a scanner commit, because the scripts did not write that line yet. Round 1 ran on
  commit `974f7f2`. Those two round 2 runs ran on the working tree that was then committed
  as `806d448`.
