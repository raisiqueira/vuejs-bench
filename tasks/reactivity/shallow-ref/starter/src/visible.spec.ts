import { describe, expect, it } from 'vitest'
import { useCatalog } from './useCatalog'

describe('useCatalog', () => {
  it('exposes the initial catalog and replacement API', () => {
    const { catalog, replaceCatalog } = useCatalog()
    expect(catalog.value.version).toBe(1)
    expect(replaceCatalog).toBeTypeOf('function')
  })
})
