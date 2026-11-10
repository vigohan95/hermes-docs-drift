# qwen3.8-27b-rename-plugin-4.txt is kept on the `evidence-raw` branch

This file is a pointer. The transcript it stands for is not in this directory on the
default branch. It is unchanged, byte for byte, here:

- branch: `evidence-raw`
- commit: `e1d26a13715bbfc68734b3d67c6dd27f7f18b6d3`
- path: `evidence/real-model/round3/qwen3.8-27b-rename-plugin-4.txt`
- sha256: `c04339b5fb8a567bab13333097ebad6eba5a1c8b2e2113a0198532b14b2007a6`
- bytes: 24262 (271 lines)

Link: <https://github.com/vigohan95/hermes-docs-drift/blob/evidence-raw/evidence/real-model/round3/qwen3.8-27b-rename-plugin-4.txt>

To read it in a clone of this repository:

```
git show e1d26a13715bbfc68734b3d67c6dd27f7f18b6d3:evidence/real-model/round3/qwen3.8-27b-rename-plugin-4.txt
```

The commit is an ancestor of the default branch, so a full clone has it without fetching the
other branch. A shallow clone does not; `git fetch --unshallow` gets it.

## The session still counts

Session 4 of `qwen3.8-27b`, request `rename`, with the plugin: started 2026-11-10T14:49:34Z,
9 chat requests, Hermes exit status 0, outcome `docs consistent`. It is in every table and
every total of [README.md](README.md) exactly as before. `benchmarks/summarize_real.py` reads
the transcript from the commit above through this file, checks the SHA-256, and prints the same
tables as when the transcript was in this directory. If it cannot read the commit, it says so
under the tables and leaves the session out, and its totals are then one session short.

## Why it is not on the default branch

`hermes plugins install` scans every file of a plugin repository before it installs it. With
this transcript in the tree the scan's verdict was `caution`, not `safe`, because of one
finding:

- rule: `echo_pipe_exec` ("echo piped to interpreter for execution"), severity critical,
  lowered one step to high because the file is a `.txt` file
- place: line 221 of the transcript

With a `caution` verdict Hermes asks for confirmation before it installs, and refuses where it
cannot ask. The install command in the main README has no `--force`, and it has to work as
written.

Line 221 is not something this plugin runs. It is a line of the recorded conversation: a
`terminal` tool call that the model issued during the session, printed by the relay as the
model sent it. The command in it is one shell line that does these things in this order:

1. changes into the session's temporary copy of the example project;
2. runs `make lint` and then the test suite;
3. prints the exit status of the test suite with the shell's print builtin;
4. makes a `notes` directory and writes a two-letter file into it;
5. runs `python -m notesync.cli` on that directory with `--dest ./out --dry-run`, with error
   output discarded;
6. after a logical OR (two vertical bars), calls `main([...])` of `notesync.cli` through
   `python -c` with the same arguments, as a fallback for step 5.

The rule looks for the print builtin, then anything on the same line, then one vertical bar
followed by the name of an interpreter. On this line the print builtin of step 3 and the
second vertical bar of the logical OR in step 6, which is followed by `python`, are enough for
it. Nothing is piped into an interpreter: the two bars mean "run this if the previous command
failed". It is a false positive.

The command is described here and not quoted, because a quote of it in this file would trip
the same rule again.

## What was done instead of editing the transcript

Nothing in the transcript was changed, and it was not renamed, compressed or moved to a
directory the scanner treats differently. It was taken out of the tree of the default branch
in one commit, and the branch `evidence-raw` was left at the commit before that one.
