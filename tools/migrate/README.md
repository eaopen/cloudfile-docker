# CloudFile one-way importer (operator tool)

`cf-import` imports bytes through authenticated Seafile/CloudFile upload APIs.
It does **not** mount external directories inside Repo/FS/Block storage. The
source can be a safe local staging directory (`local:///...`) or a Filestash
reference source (`filestash://alias/path`). Filestash remains a separate
application and credentials remain in private token files.

## Recommended sequence

1. Use `cf-import create` to initialize a **per-repository and target** job
   directory with private tokens. Reserve the target library exclusively during
   `apply`. Reuse the same job directory for later increments and recovery.
2. `cf-import check JOB` enumerates changes and stores the current target HEAD.
   `cf-import plan JOB --limit 100` shows the planned operations.
3. `cf-import probe JOB` asks the target for its **current** HEAD, but does
   not mutate the job. `may_retry_under_exclusive_lock=true` is only an
   indication that the HEAD matches the saved plan; you must **still** hold
   exclusive access and use `apply --exclusive`.
4. `cf-import apply JOB --exclusive` imports the planned bytes, validates
   target SHA-256, and advances the saved HEAD. Never bypass a conflict.
5. `cf-import report JOB` gives an offline, read-only handoff report.
   Re-run `check` only after a previous apply completed.

A changed child file does **not** cause its parent directory to be re-imported
merely because directory mtime changed. Source files are compared using
size/mtime for planning, then hashed and verified when uploading; if a source
can change its bytes without changing size/mtime, the producer must provide
a stable snapshot or create a fresh controlled import. This is not a real-time
two-way synchronization engine.

## Interrupted upload / conflict

When a response was lost after a potential server Commit, the saved plan HEAD
may no longer match the live HEAD. `probe` deliberately reports
`HEAD_MISMATCH` and **does not** automatically mark the file as completed or
blindly retry it. Inspect target contents, file versions and current source
under an operator-controlled window, then plan a fresh import if appropriate.

Source deletions are only `delete_candidate` reports. No target deletion is
performed; the tool does not introduce persistent job tables in Seafile.
