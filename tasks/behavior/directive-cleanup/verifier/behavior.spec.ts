import { mount } from '@vue/test-utils'
import { defineComponent, h, withDirectives } from 'vue'
import { expect, it, vi } from 'vitest'
import { vClickOutside } from '../src/clickOutside'
it('fires outside while mounted, then releases the listener', () => {
  const outside = vi.fn()
  const Host = defineComponent({
    setup: () => () => withDirectives(h('div', 'Panel'), [[vClickOutside, outside]]),
  })
  const first = mount(Host)
  document.body.click()
  expect(outside).toHaveBeenCalledTimes(1)
  first.unmount()
  document.body.click()
  expect(outside).toHaveBeenCalledTimes(1)
  const second = mount(Host)
  document.body.click()
  expect(outside).toHaveBeenCalledTimes(2)
  second.unmount()
})
