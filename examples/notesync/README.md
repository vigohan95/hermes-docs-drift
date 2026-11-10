# notesync

Copy Markdown notes to a folder, one file per note.

## Usage

```sh
notesync ./notes --output-dir ./backup
notesync ./notes --dry-run
```

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--output-dir` | `./out` | where the copies go |
| `--timeout` | `30` | seconds to wait for a locked file |
| `--dry-run` | off | print what would be copied |

Set `NOTESYNC_TOKEN` to enable the remote upload.

More in [the configuration guide](docs/configuration.md).

## Development

```sh
make test
```
