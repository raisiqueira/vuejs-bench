import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
it('renders both rows', () => {
  const wrapper = mount(App)
  expect(wrapper.findAll('li')).toHaveLength(2)
})
