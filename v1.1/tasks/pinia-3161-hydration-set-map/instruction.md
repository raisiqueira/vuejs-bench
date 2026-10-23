# Reactive Set/Map state is unioned instead of replaced during SSR hydration

This repository is Pinia. The library source is in `packages/pinia`.

When a setup store has a `reactive(new Set([...]))` or `reactive(new Map([...]))`
state property with default entries, SSR hydration unions the client defaults
with the server state instead of replacing them. Entries that the server removed
survive on the client.

## Reproduction

```ts
const useStore = defineStore('main', () => {
  const setReactive = reactive(new Set(['default']))
  return { setReactive }
})

const pinia = createPinia()
pinia.state.value.main = { setReactive: new Set(['a']) } // server state
setActivePinia(pinia)

const store = useStore()
console.log([...store.setReactive]) // ['default', 'a'] <- wrong, should be ['a']
```

## Expected behavior

The server state is authoritative during hydration. A `ref()` state property is
already replaced by the server value. Reactive `Set` and `Map` state must also
be replaced, so only the server entries remain. This applies to a Set/Map that
is a top-level state property and to a Set/Map nested inside a reactive object.
