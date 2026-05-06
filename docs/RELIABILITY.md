# Reliability

## Runtime expectations

- Remote operations can fail due to auth, network, Modal API state, missing volume/path, or consistency lag.
- Index can be stale; commands must expose freshness metadata.
- Cache can be partial; commands must distinguish metadata-only, content-cached, and content-indexed states.

## Failure behavior

- Machine-readable errors for agent branching.
- Retry only on clearly retryable remote failures.
- Never continue after partial destructive failures without reporting exact affected paths.

## Concurrent mutation stance

Modal Volumes v2 make distinct-file concurrent writes much safer and more scalable than v1, but they do not remove same-file last-write-wins semantics. `mfs` should therefore treat write coordination as a product decision, not an implicit guarantee.

Default reliability policy:

- Reads and metadata queries may run concurrently.
- MVP includes thin write primitives: `get`, `put`, `rm`, and `cp`.
- Writes to different target paths may run concurrently.
- Overwrite/delete/rename operations require explicit flags.
- MVP does not include a mutation queue.
- If `mfs` later adds a mutation queue, call it a cooperative queue, not a lock manager.
- For same-path writes, prefer compare-before-write using known hashes/manifests when available.
