import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
it('starts with the editor closed', () => {
  expect(mount(App).find('input').exists()).toBe(false)
})
