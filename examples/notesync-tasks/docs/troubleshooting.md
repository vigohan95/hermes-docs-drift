# Troubleshooting

## Uploads fail on a slow connection

Raise the time limit, for example `--timeout 120`. With the default of 3 retries a file is
given four attempts in total before notesync moves on.

## Copies are incomplete on a network drive

Run with `--legacy-sync`, which copies the files one by one and flushes after each:

```sh
notesync ./notes --legacy-sync
```

## The token is not picked up in a container

Mount the token as a file and point `NOTESYNC_TOKEN_FILE` at it.
