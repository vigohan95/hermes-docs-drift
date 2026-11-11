# Held-out set 3: how the 12 repositories were chosen

Written on 2026-11-10 before the search below was run and before anything was cloned.
The scanner was not changed after this set was scanned.

(Added on 2026-11-11: version 0.1.1 changed the scanner for the reasons in `SECURITY.md`,
none of them a result on this set. Scanned again with it, the 12 repositories give the same
findings; see `rescan.txt`.)

## The rule

1. Ask the GitHub search API for repositories with

   ```
   topic:cli stars:300..5000 pushed:>=2026-08-12 archived:false fork:false
   ```

   sorted by stars, highest first, 100 per page (`gh api "search/repositories?q=...&sort=stars&order=desc&per_page=100&page=N"`).
   `pushed:>=2026-08-12` is 90 days before today.
2. Walk the result in that order. For each repository fetch the README of the default
   branch through the API and count, with these two patterns,

   - long flags: `(?<![\w-])--[a-z][a-z0-9-]{2,}`
   - environment-style names: `\b[A-Z][A-Z0-9]{2,}_[A-Z0-9_]{2,}\b`

   Skip the repository unless the README has at least 5 different long flags or at least
   3 different environment-style names. This is the test for "a command-line tool whose
   README documents flags or variables"; nobody reads the README to decide.
3. Also skip a repository when
   - it is one of the 24 in `targets.txt`, or Hermes Agent, or a repository of the same owner as one of those;
   - its size reported by the API is above 150 MB (clone time on this machine);
   - 4 repositories with the same primary language (the API's `language` field) are already taken, or the field is empty;
   - its description or README marks it as a list of links, a tutorial or a book rather than a program (the word "awesome", "tutorial", "course", "book" or "list of" in the repository name or description).
4. Take the first 12 that remain. Clone each at the head of its default branch and record the commit.
5. Scan each once with all nine checks using `benchmarks/run_scans.py` at the scanner commit of that moment.
   Label every finding by hand. Report found and true for the default checks and for the opt-in checks.
   No check is changed afterwards because of these results.

The skipped repositories and the reason for each are written to `heldout3-selection.txt` by the
script that applies the rule.
