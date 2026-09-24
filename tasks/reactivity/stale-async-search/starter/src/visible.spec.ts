import { expect, it } from 'vitest'
import { ref } from 'vue'
import { useSearch } from './useSearch'
it('exposes search state', () => {
  const search = useSearch(ref(''), async () => [])
  expect(search.results.value).toEqual([])
})
