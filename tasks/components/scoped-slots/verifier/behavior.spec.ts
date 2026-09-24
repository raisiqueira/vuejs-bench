import { mount } from '@vue/test-utils'
import { h } from 'vue'
import { expect, it } from 'vitest'
import GenericList from '../src/GenericList.vue'
it('provides item data to slots and omits an absent header wrapper', () => {
  const wrapper = mount(GenericList, {
    props: { items: ['Alpha', 'Beta'] },
    slots: { item: ({ item }: { item?: string }) => h('strong', item?.toUpperCase() ?? 'missing') },
  })
  expect(wrapper.findAll('strong').map(item => item.text())).toEqual(['ALPHA', 'BETA'])
  expect(wrapper.find('.list-header').exists()).toBe(false)
  const withHeader = mount(GenericList, {
    props: { items: [] },
    slots: { header: 'Names' },
  })
  expect(withHeader.get('.list-header').text()).toBe('Names')
})
