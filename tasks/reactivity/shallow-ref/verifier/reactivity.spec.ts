import { isReactive, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCatalog, type Catalog } from '../src/useCatalog'

describe('catalog reactivity behavior', () => {
  it('keeps nested records plain while replacing the root', () => {
    const { catalog } = useCatalog()
    expect(isReactive(catalog.value)).toBe(false)
    expect(isReactive(catalog.value.items[0])).toBe(false)
    expect(isReactive(catalog.value.items[0].details)).toBe(false)
  })

  it('still updates the root value when a catalog is replaced', async () => {
    const { catalog, replaceCatalog } = useCatalog()
    const replacement: Catalog = { version: 2, items: [] }
    replaceCatalog(replacement)
    await nextTick()
    expect(catalog.value).toBe(replacement)
    expect(catalog.value.version).toBe(2)
  })
})
