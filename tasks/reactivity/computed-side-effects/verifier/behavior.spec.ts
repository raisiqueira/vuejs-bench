import { expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { useOrder } from '../src/useOrder'
it('keeps reads pure and audits changed totals once', async () => {
  const audit = vi.fn()
  const order = useOrder(audit)
  expect(order.total.value).toBe(10)
  expect(order.total.value).toBe(10)
  expect(audit).not.toHaveBeenCalled()
  order.quantity.value = 2
  await nextTick()
  expect(order.total.value).toBe(20)
  expect(audit).toHaveBeenCalledExactlyOnceWith(20)
  order.price.value = 12
  await nextTick()
  expect(order.total.value).toBe(24)
  expect(audit.mock.calls.map(call => call[0])).toEqual([20, 24])
})
