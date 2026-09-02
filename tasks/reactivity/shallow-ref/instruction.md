The catalog in `useCatalog.ts` is effectively immutable internally, but the
current implementation deeply proxies every nested record. Improve the
reactivity strategy so that replacing the catalog still updates consumers,
while nested records remain plain immutable data.

Preserve the existing public API and the visible behavior. Do not remove
existing tests. The catalog should only need root-level reactivity.
