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
