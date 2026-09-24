import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
it('synchronizes edits and parent resets', async () => {
  const wrapper = mount(App)
  await wrapper.get('input').setValue('Lin')
  expect(wrapper.get('[data-testid="name"]').text()).toBe('Lin')
  await wrapper.get('button').trigger('click')
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Grace')
})
