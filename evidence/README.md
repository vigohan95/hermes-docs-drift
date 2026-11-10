# Evidence

Everything here was produced by running the code in this repository on one Windows 11
machine on 2026-11-10. Nothing was edited afterwards except where a file says so.

## Which run is which

| Name in file paths | Scanner commit | What was scanned |
| --- | --- | --- |
| `round1` | `974f7f2` | tuning set; held-out 1 for the first time |
| `round2` | `806d448` | tuning set and held-out 1 again; held-out 2 for the first time |
| `round3` | `8ff4f2c` | all 24 repositories |
| `final` | `b7ba05d` | all 24 repositories, and Hermes Agent |

Commits after `b7ba05d` change the elapsed-time field of change scans, the README and the
files in this directory. They do not change a check, so the final run was not repeated.

The three sets and the commit each repository was scanned at are in `targets.txt`.

## Files

| File | What it is |
| --- | --- |
| `targets.txt` | The 24 repositories and Hermes Agent, with the commit of each clone. Written by reading `git rev-parse HEAD` in every clone. |
| `scans/<run>-<set>/*.json` | Every finding of a whole-repository scan with all nine checks, one file per repository. Written by `benchmarks/run_scans.py`. `run.log` has the scanner commit and the times. |
| `labels.json` | One hand label (true or false, with the reason) for every distinct finding in `scans/`. |
| `precision.txt` | Output of `python benchmarks/precision.py evidence/scans evidence/labels.json`. |
| `injected/<run>-<set>/*.json` | Result of every injected change. Written by `benchmarks/inject.py`. |
| `recall.txt` | Output of `benchmarks/summarize_inject.py` for every directory in `injected/`. |
| `hermes-self/round3/hermes-agent.json` | Scan of Hermes Agent with scanner `8ff4f2c`, before the rules that followed from it. |
| `hermes-self/final/hermes-agent.json` | Scan of Hermes Agent with scanner `b7ba05d`. |
| `hermes-self/labels.json` | Hand labels for the 33 default-check findings of that final scan. Its opt-in findings are not labelled. |
| `demo-rename.txt`, `demo-forget.txt` | Output of `python demo/run_demo.py rename` and `forget` against Hermes Agent `b7db40d` with the plugin installed from commit `2071824`. |
| `demo-without-plugin.txt` | The `rename` script run against a Hermes home in which the plugin is not installed. The driver's checks fail, as they should; the file is kept for the timing of Hermes' `patch` tool without the hooks. The line `plugin:` at its top names the source checkout, not an installed copy. |
| `validate.txt` | Output of `hermes plugins validate` for this repository. |
| `slash-command.txt` | The `/drift` command was not typed in an interactive Hermes chat, because that needs a configured model provider. A short script asked Hermes' plugin manager (`hermes_cli.plugins`) for the handler the plugin registered for `/drift` and called it. The file has the script, quoted at the top, and its output. |

## Things to know when reading the files

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
- The `run.log` files of round 1, and of round 2 for the tuning set and held-out 1, do not
  name a scanner commit, because the scripts did not write that line yet. Round 1 ran on
  commit `974f7f2`. Those two round 2 runs ran on the working tree that was then committed
  as `806d448`.
