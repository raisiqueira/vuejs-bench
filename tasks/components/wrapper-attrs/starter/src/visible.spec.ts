import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import BaseButton from './BaseButton.vue'
it('renders the button slot', () => {
  expect(mount(BaseButton, { slots: { default: 'Save' } }).get('button').text()).toBe('Save')
})
