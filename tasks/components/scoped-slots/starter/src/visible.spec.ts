import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import GenericList from './GenericList.vue'
it('renders fallback items', () => {
  expect(mount(GenericList, { props: { items: ['Alpha'] } }).get('li').text()).toBe('Alpha')
})
