import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
it('uses defineModel for the named model', () => {
  const source = readFileSync(resolve('src/SearchField.vue'), 'utf8')
  expect(source).toMatch(/defineModel\s*(?:<[^>]+>)?\s*\(\s*['"]query['"]/)
})
it('synchronizes named model edits, modifier, and parent resets', async () => {
  const wrapper = mount(App)
  await wrapper.get('input').setValue('  beta  ')
  expect(wrapper.get('[data-testid="query"]').text()).toBe('beta')
  await wrapper.get('button').trigger('click')
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('reset')
})
