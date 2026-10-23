# useFetch: a superseded request can overwrite fresh data with a stale response

This repository is VueUse. The `useFetch` composable is in `packages/core`.

When a newer request starts, `useFetch` already makes sure that an error from an
older, superseded request cannot overwrite the state of the newer request. A
successful response from a superseded request does not get the same treatment:
when it finally resolves, it overwrites fresh data with stale data.

## Reproduction

```ts
const url = ref('/slow')
const { data } = useFetch(url, { refetch: true }).json()

// request A starts for /slow (slow response)
url.value = '/fast' // request B starts

// B resolves first: data.value is correctly set to B's data
// A resolves later (it was already superseded): data.value is
// silently overwritten with A's stale response
```

## Expected behavior

After a newer request has started, a superseded request must not write its
result into the returned state (`data`, `response`, `statusCode`), whether it
succeeds or fails. The state must always show the latest request.

The `onFetchResponse` event keeps its current behavior: it still fires for every
response that completes, including a superseded one.
