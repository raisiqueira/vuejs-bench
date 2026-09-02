The counter side effect in `useWatchedCounter.ts` no longer fires when the
state changes. Restore the watcher so that each increment records one event.

Preserve the existing composable API and behavior. Do not remove existing
tests or silence Vue warnings as a workaround.
