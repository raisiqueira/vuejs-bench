import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'
it('shows the initial query', () => {
  expect((mount(App).get('input').element as HTMLInputElement).value).toBe('alpha')
})
