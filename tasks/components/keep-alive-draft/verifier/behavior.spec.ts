import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
import { setAnnouncement } from '../src/announcement'
it('preserves local draft and refreshes data on activation', async () => {
  setAnnouncement('First notice')
  const wrapper = mount(App)
  await wrapper.get('input').setValue('Unsent work')
  await wrapper.get('button:nth-of-type(2)').trigger('click')
  setAnnouncement('New notice')
  await wrapper.get('button:nth-of-type(1)').trigger('click')
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Unsent work')
  expect(wrapper.get('[data-testid="announcement"]').text()).toBe('New notice')
  wrapper.unmount()
})
