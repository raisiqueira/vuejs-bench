import { expect, it } from 'vitest'
import { useOrder } from './useOrder'
it('computes the initial total', () => {
  const order = useOrder(() => {})
  expect(order.total.value).toBe(10)
})
