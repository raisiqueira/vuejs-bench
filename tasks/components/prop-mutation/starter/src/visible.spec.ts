import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
it('starts at zero', () => {
  expect(mount(App).get('[data-testid="parent-count"]').text()).toBe('0')
})
