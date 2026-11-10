# notesync

Copies Markdown notes to a folder, one file per note, and uploads the copies when a token
is set.

## Usage

```sh
notesync ./notes --output-dir ./backup
```

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--output-dir` | `./out` | where the copies go |
| `--timeout` | `30` | seconds to wait for the server |
| `--retries` | `3` | how often a failed upload is tried again |
| `--legacy-sync` | off | deprecated: copy the files one by one |

A failed upload is tried again 3 times before notesync gives up on that file.

## Upload

Set `NOTESYNC_TOKEN` to enable the upload. More in
[the configuration guide](docs/configuration.md); if something goes wrong, see
[troubleshooting](docs/troubleshooting.md).

## Development

```sh
make test
```
