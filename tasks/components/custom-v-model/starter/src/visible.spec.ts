import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
it('starts with the parent name', () => {
  expect((mount(App).get('input').element as HTMLInputElement).value).toBe('Ada')
})
