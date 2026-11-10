# Held-out 3, injected drift: what was read by hand

Run once on 2026-11-10 with the scanner at commit `35e6564`, on the 12 repositories of
held-out 3 at the commits named in each JSON file. Nothing in the scanner was changed
afterwards because of this run.

## Numbers

- 221 mutations were made and counted. 24 more could not be made (a Go project whose flag
  definitions carry no dashes, or a mutation that changed nothing) and are not counted.
- 3 of the 12 repositories gave no candidate at all (red-data-tools/YouPlot,
  carloscuesta/gitmoji-cli, speedyapply/JobSpy): no flag, variable, script, target or link
  that both the code and a checked doc contain.
- Detected with the pre-edit index (what the hooks do): 211 of 221.
- Detected by a plain scan of the changed tree: 83 of 221.
- Findings after a mutation that were about anything other than the item that was changed:
  **0**. `other_new_findings` is empty in every row. In this run the list is not cut at ten
  entries per mutation, as it was in the earlier runs.
- The 211 detections came with 455 findings in total, because one renamed name is usually
  mentioned on several doc lines. All 455 name the mutated item.

The 10 misses are listed at the end of the `round5-heldout3` block in `../../recall.txt`.

## Is a detection a useful message? First reported line of each flag and variable

"Detected" only means a finding with the right check and the right name appeared. It does
not say the doc line it points at is a statement about this program. For path, npm and make
mutations there is nothing to judge (the doc links a file, or runs a script or target, that
is gone). For the 131 flag and variable detections, the first doc line each one reported was
read, one line at a time and without the surrounding text. The other lines of the same
detections (the rest of the 455) were not read.

Variables, 38 detections:

- 33 point at a line that says something about a variable this project's code read before
  the mutation.
- 5 point at a line that uses the same name for something else. If an edit to the real code
  did remove the last read of that variable, the message on these lines would be a false
  alarm:
  - `PATH`, three times (KKKKhazix/agent-autoloop `INSTALL.md:30`, alexellis/arkade
    `README.md:214`, tmux-python/tmuxp `docs/topics/troubleshooting.md:5`). Each line is
    about the search path of the user's shell.
  - `CODEX_SESSION_ID` (mvanhorn/cli-printing-press
    `skills/printing-press/phases/01-preflight.md:558`): the line is a shell test inside a
    skill, and the code that read the variable is a test template.
  - `STEAM_API_KEY` (mvanhorn/cli-printing-press
    `docs/brainstorms/2026-03-31-auth-error-handling-requirements.md:19`): the line is an
    example of an error message in a requirements note.
- Two more are loose: `HOME` in mvanhorn/cli-printing-press `AGENTS.md:116` and in
  Jia-Ethan/codex-keysmith `docs/reference.md:247` are about a different part of the project
  than the file whose read was renamed. They are counted with the 33.

Flags, 93 detections of 58 distinct flags: every first line that was read is a command of
the project itself or a description of its own flag. None was seen to be about another
program's flag of the same name.

So on these repositories the edit-time path reported nothing unrelated to the edit, and of
the 131 first lines read, 5 would not help a reader. That is a statement about mutations a
script made (renames and removals of names the docs contain), not about edits a person or a
model would make.
