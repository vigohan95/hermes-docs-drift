# Configuration

`notesync` reads one environment variable:

- `NOTESYNC_TOKEN`: token for the remote upload. Without it nothing is uploaded.

To write the copies somewhere else, pass `--output-dir`:

```sh
notesync ./notes --output-dir /mnt/backup/notes
```
