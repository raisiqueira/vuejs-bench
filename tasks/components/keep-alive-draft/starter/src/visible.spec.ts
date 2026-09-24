import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
it('opens the draft view', () => {
  expect(mount(App).find('input').exists()).toBe(true)
})
