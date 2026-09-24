import { expect, it } from 'vitest'
import { nextTick } from 'vue'
import { useProducts } from '../src/useProducts'
it('derives count and total from every product change', async () => {
  const catalog = useProducts()
  catalog.add({ id: 2, price: 5, quantity: 3 })
  await nextTick()
  expect([catalog.count.value, catalog.total.value]).toEqual([5, 35])
  catalog.update(1, 8, 4)
  await nextTick()
  expect([catalog.count.value, catalog.total.value]).toEqual([7, 47])
  catalog.remove(2)
  await nextTick()
  expect([catalog.count.value, catalog.total.value]).toEqual([4, 32])
})
