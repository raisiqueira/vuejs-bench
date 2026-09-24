import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
it('uses useTemplateRef for the editor element', () => {
  const source = readFileSync(resolve('src/App.vue'), 'utf8')
  expect(source).toMatch(/useTemplateRef\s*(?:<[^>]+>)?\s*\(\s*['"]editor['"]\s*\)/)
})
it('focuses on each open and clears the conditional ref on close', async () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const wrapper = mount(App, { attachTo: host })
  await wrapper.get('button').trigger('click')
  expect(document.activeElement).toBe(wrapper.get('input').element)
  await wrapper.get('button').trigger('click')
  expect(wrapper.find('input').exists()).toBe(false)
  await wrapper.get('button').trigger('click')
  expect(document.activeElement).toBe(wrapper.get('input').element)
  wrapper.unmount()
  host.remove()
})
