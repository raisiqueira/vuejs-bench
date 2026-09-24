import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import BaseButton from '../src/BaseButton.vue'
it('forwards attributes and one click to the actual button', async () => {
  const click = vi.fn()
  const wrapper = mount(BaseButton, {
    attrs: { 'aria-label': 'Save changes', title: 'Save now', onClick: click },
    slots: { default: 'Save' },
  })
  const button = wrapper.get('button')
  expect(button.attributes('aria-label')).toBe('Save changes')
  expect(button.attributes('title')).toBe('Save now')
  await button.trigger('click')
  expect(click).toHaveBeenCalledTimes(1)
  const disabled = mount(BaseButton, { attrs: { disabled: true } })
  expect(disabled.get('button').attributes('disabled')).toBeDefined()
})
