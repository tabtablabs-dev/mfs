# Reliability

## Runtime expectations

- Remote operations can fail due to auth, network, Modal API state, missing volume/path, or consistency lag.
- Index can be stale; commands must expose freshness metadata.
- Cache can be partial; commands must distinguish metadata-only, content-cached, and content-indexed states.

## Failure behavior

- Machine-readable errors for agent branching.
- Retry only on clearly retryable remote failures.
- Never continue after partial destructive failures without reporting exact affected paths.
