# Retry policy for the sync worker

## Summary

Failed uploads now back off exponentially. The fixed delay overloaded the gateway after an outage.

## Changes

- `UploadJob` reads its delay from `RetryPolicy`.
- Delays are 1, 2, 4, and 8 seconds, capped at 60.
- `SyncQueue` no longer holds its lock during the network call.
- After 5 attempts, the app shows a sync error on Home.

## Rollout

The `sync_backoff_v2` flag controls the change. It is off in production and on in staging.

## Testing

- Unit tests pin the delays and the cap.
- Manual check: turn on airplane mode, queue an upload, and turn it off again.
