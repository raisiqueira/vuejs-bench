import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
it('keeps parent and child in sync in both directions', async () => {
  const wrapper = mount(App)
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('[data-testid="parent-count"]').text()).toBe('1')
  expect(wrapper.get('button').text()).toContain('1')
  await wrapper.get('[data-testid="reset"]').trigger('click')
  expect(wrapper.get('button').text()).toContain('0')
})
