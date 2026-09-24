import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import SaveControl from '../src/SaveControl.vue'
it('uses a named native button and preserves the activate event', async () => {
  const wrapper = mount(SaveControl)
  const button = wrapper.get('button')
  expect(button.classes()).toContain('save-control')
  expect(button.text().trim() || button.attributes('aria-label')).toBeTruthy()
  expect(button.attributes('type')).toBe('button')
  await button.trigger('click')
  expect(wrapper.emitted('activate')).toHaveLength(1)
})
