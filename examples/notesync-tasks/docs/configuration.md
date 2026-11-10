# Configuration

## Environment

- `NOTESYNC_TOKEN`: token for the upload.
- `NOTESYNC_TOKEN_FILE`: path of a file that holds the token. Used when `NOTESYNC_TOKEN`
  is not set.

## Retries

notesync retries a failed upload 3 times by default. To turn retrying off:

```sh
notesync ./notes --retries 0
```

## Where the copies go

Pass `--output-dir`:

```sh
notesync ./notes --output-dir /mnt/backup/notes
```
