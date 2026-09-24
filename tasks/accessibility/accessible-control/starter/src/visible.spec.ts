import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import SaveControl from './SaveControl.vue'
it('announces its action', () => {
  expect(mount(SaveControl).text()).toBe('Save')
})
