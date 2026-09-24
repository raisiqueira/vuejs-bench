import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
it('preserves row drafts by record identity after reorder', async () => {
  const wrapper = mount(App)
  await wrapper.get('[data-id="1"] input').setValue('Edited Alpha')
  await wrapper.get('button').trigger('click')
  expect((wrapper.get('[data-id="1"] input').element as HTMLInputElement).value).toBe('Edited Alpha')
  expect((wrapper.get('[data-id="2"] input').element as HTMLInputElement).value).toBe('Beta')
})
