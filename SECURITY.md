# Security

## What the plugin does on a machine

The same list as "What it runs and reads" in the [README](README.md):

- It runs `git` in the repository being checked and no other program. It uses six
  subcommands, none of which writes: `ls-files`, `status`, `cat-file blob`,
  `diff --cached --name-only`, `check-ignore` and `config --get-regexp`.
- It reads text files in that repository and `.git/config`. It does not open `.env` files,
  key files or credential stores; the list of skipped names is in `docsdrift/repo.py`.
- It writes nothing to disk, makes no network request and sends no telemetry.
- It has no dependencies outside the Python standard library, no binaries and no code that
  updates itself.

## A repository someone else wrote

An agent is often pointed at a repository its user did not write. Three things in such a
repository are treated as untrusted: its git config, its links, and the text of its files.
The tests for this section are in `tests/test_hardening.py`.

### Git config

Git can start a program that `.git/config` names. Every git child gets options that win over
that config, and an environment that carries nothing it does not need.

| What could run or be reached | How it is turned off |
| --- | --- |
| `core.fsmonitor`, started by `ls-files` and `status` | `-c core.fsmonitor=false` |
| hooks | `-c core.hooksPath=` the null device |
| the untracked cache, which git writes into `.git/index` | `-c core.untrackedCache=false` |
| clean, smudge and process filters, started when `status` has to hash a file | the drivers are listed with `git config --get-regexp` and each is set to empty with `-c` |
| textconv and external diff programs | `--no-textconv`, `--no-ext-diff` |
| submodules | `--ignore-submodules=all`; git is only ever run in the top-level repository |
| `gpg.program`, started by `git show REV:path` when `path` is a submodule at `REV` and `log.showSignature` is set | the text of a file at a revision is read with `git cat-file blob`, which prints a blob or fails |
| a fetch of a missing object in a partial clone, through a transport the config names | `GIT_NO_LAZY_FETCH=1`, `GIT_ALLOW_PROTOCOL` with no protocol in it, and `protocol.allow=never` |
| `core.worktree`, which points git at another directory | `GIT_WORK_TREE` is set to the repository being checked |
| a rewrite of `.git/index` by `git diff REV`, which refreshes the index and saves it | `git diff REV` is not run: `status` and `diff --cached REV` together give the same list and do not write; `-c diff.autoRefreshIndex=false` is set as well |
| a revision that git would read as an option | a revision that starts with `-` is refused before git is started |
| a pager or a prompt | `--no-pager`, `GIT_TERMINAL_PROMPT=0`, no terminal on standard input |

If the filter drivers cannot be listed, or one has a name that cannot be written in a `-c`
option, `status` and `diff` are not run. The comparison with `HEAD` is then not available,
as in a directory without git.

With the filters off, git hashes a file as it is on disk. A file kept in Git LFS can then
be listed as changed when it is not, and its committed text is read as the pointer file.
The plugin reads docs and source text, so this matters only for a repository that keeps
those in LFS.

The environment of a git child is `PATH`, `HOME`, `LANG` and `LC_ALL` from the parent
process (on Windows also `SYSTEMROOT`, `TEMP`, `TMP` and `USERPROFILE`), plus
`GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, `GIT_NO_LAZY_FETCH=1`,
`GIT_ALLOW_PROTOCOL=:`, `GIT_WORK_TREE` (the repository being checked) and
`GIT_CEILING_DIRECTORIES` (the directory above it). Provider keys and tokens in the agent's
environment do not reach git, and neither does an inherited `GIT_DIR` or `GIT_CONFIG_*`; an
inherited `GIT_WORK_TREE` is replaced. The user's own `~/.gitconfig` is still read by git;
it belongs to the user, not to the repository.

What the tests do: one repository names a program in `core.fsmonitor`, another names a clean
filter through `.gitattributes`, a third has a submodule entry whose commit carries a
signature and names a program in `gpg.program`. Each test first runs the plain git command
(`git status`, `git show`) and checks that the program ran, so that the test cannot pass on
a git that would not have run it anyway, and then checks that a scan or a comparison does
not run it. Other tests set `core.worktree` to another directory and check that its files
are not listed, compare the bytes of `.git/index` before and after a comparison with a
revision, and record every git child of a scan and of a comparison and check the
subcommand, the options and the environment of each. They ran with git 2.54 on Windows and
git 2.43 on Ubuntu before the release. In CI the same tests run on Linux, macOS and
Windows, with git 2.56 on all three for this version. A test whose first step fails,
because that git does not start the program, is skipped and not counted as passed, and
pytest prints the reason for every skipped test; in the CI run for this version none of
these tests was skipped. Older versions of git were not tried.

That `GIT_ALLOW_PROTOCOL=:` wins over a `protocol.<name>.allow=always` in the config was
tried by hand with the same two versions of git, not in a test: no test fetches anything.

### Links

A tracked `docs/notes.md` can be a symbolic link to a file outside the repository. A link
(on Windows also a junction) is followed only when the file it leads to

- is inside the repository, after resolving every link on the way,
- is not inside a `.git` directory, and
- does not have a name that is never read (`.env`, key files, credential stores).

The same rule applies to a file below a linked directory, and to all three ways the plugin
touches a path: reading it, asking whether it exists, and asking for its size and
modification time. A path with `..` that leaves the repository, or an absolute path, is
refused before the file system is asked. A file that is refused looks like a file that is
not there.

`.git` means a path component with that name at any depth and in any letter case, so that
`vendor/lib/.git/config` and, on a file system that ignores case, `.GIT/config` are refused
too, with or without a link. A link target is also compared with the repository's own `.git`
by identity (device and inode), for a spelling that no comparison of names finds.

For a file with a name that is never read, the one thing the plugin asks the file system is
whether it exists (a doc that links to `.env` is not told the file is missing). Its size and
modification time are not asked.

On Windows a few more spellings are refused, because they open a file under another name:
a component with `:` in it (`notes.md::$DATA`), one that ends in a dot or a space, and the
device names (`NUL`, `CON`, `COM1` and the others). A path with `~` in it can be a short
name (`GIT~1`); it is resolved and judged by the name it resolves to, like a link.

A name that git lists is used only when it is a plain relative path: no `..`, no empty
component and none of the spellings above. Git for Windows lists the files behind a
junction as untracked files of the repository; those names are dropped. Without git, the
directory walk does not enter a linked directory.

The tests make real symbolic links where the system allows it and junctions for directories
where it does not. On a Windows machine without the right to create symbolic links the tests
for linked files are skipped; for this version they ran under Ubuntu and on the CI runners
of all three systems, where links can be made, and the tests for linked directories also on
a Windows machine with junctions. The test for the junction listing always makes junctions,
because git does not list the files behind a symbolic link to a directory; it runs on
Windows only, like the tests for the Windows spellings.

Known limits:

- A hard link to a file outside the repository cannot be told from the file itself, and is
  read like any other file of the repository.
- Between the check of a path and the opening of the file there is a moment in which the
  path can be made to lead somewhere else by a program that runs at the same time.
- Names are compared by letter case only. A file system that treats two other spellings as
  the same name (Unicode normalisation on macOS) is covered for the repository's own `.git`
  by the identity check, and not for a `.git` directory deeper in the tree.

### Slow input

Python cannot interrupt a regular-expression search, and some patterns need time that grows
with the square or the cube of the length of a line. Version 0.1.0 had eleven of those. The
worst was the pattern for code spans: on the machine these numbers come from it needed about
0.7 seconds for one line of 4,000 backticks, and at 8,000 the search was stopped after 4
seconds. They are replaced by patterns, or in one case a small scanner, that work in linear
time.

`benchmarks/regex_timing.py` takes every regular expression out of the source with `ast`
(94 calls, 91 different patterns in this version) and times each one on long repetitive
strings of 32,000 characters: 144 short units such as a space, a backtick, `<a `, `](` or a
blank line, repeated, with a few prefixes and suffixes, plus the words of the pattern itself.
That is between 2,160 and 5,676 strings for a pattern and 357,786 in all. The output of the
run for this version is [evidence/regex-timing.txt](evidence/regex-timing.txt). In it no
pattern needed more than 0.033 seconds for a string, with one exception: the pattern that
reads `console_scripts` entries is quadratic. Its input is cut to 2,000 characters by the
pattern around it, and at that length it took up to 0.055 seconds. This is a test over chosen
inputs, not a proof; an input that none of the units resembles can still be slow.

That is why there is a second line of defence. One call of a hook has one time limit
(`hook_time_budget_s`, 8 seconds unless configured), counted from the moment the hook is
entered. Waiting for another scan, every git child and every scan in the call share it; no
git child is started after it and a running one is stopped; the checks look at the clock
between doc files. A hook therefore returns late only by the time of the one search it is
in. Hermes blocks a tool call whose `pre_tool_call` hook has not answered after 30 seconds.

Known gap: when `pre_tool_call` cannot get the lock in time because a long
`docs_drift_scan` is running in the same process, no baseline is taken for that edit. In a
git repository the baseline is then rebuilt from `HEAD`; outside git that edit is not
checked.

## Text from the repository reaches the model

A finding quotes one line of a doc file and one line of code, each cut at 180 characters,
and puts them in the result of the `write_file` or `patch` call. `docs_drift_explain` adds a
few lines around each when the agent asks for them. Those lines come from the repository
being edited, so a repository written to mislead an agent can place words there. The agent
can read the same lines with its own file tools, and the plugin adds text from nowhere else,
but the quotes are not filtered. Since 0.1.1 a quoted line cannot come from outside the
repository through a link.

The plugin cannot approve a tool call, run a slash command or answer a confirmation prompt.
The reminder before the end of a turn is sent at most once per turn.

## Reporting a problem

Use "Report a vulnerability" on the Security tab of
<https://github.com/vigohan95/hermes-docs-drift> for anything that should not be public yet.
For everything else, open an issue. Fixes go to `main`; there are no maintained older
versions.
