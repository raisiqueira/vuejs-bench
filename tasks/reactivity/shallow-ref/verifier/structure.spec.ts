import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('root-only reactivity intent', () => {
  it('uses the explicit shallowRef API', () => {
    // Deep-vs-shallow performance is not fully observable in a small fixture;
    // this narrow structural assertion protects the stated optimization intent.
    const source = readFileSync(resolve(process.cwd(), 'src/useCatalog.ts'), 'utf8')
    expect(source).toContain('shallowRef')
  })
})
