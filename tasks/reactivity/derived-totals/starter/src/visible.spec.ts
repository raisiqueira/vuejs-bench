import { expect, it } from 'vitest'
import { useProducts } from './useProducts'
it('starts with one product worth twenty', () => {
  const { count, total } = useProducts()
  expect(count.value).toBe(2)
  expect(total.value).toBe(20)
})
