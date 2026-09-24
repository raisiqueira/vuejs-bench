import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { expect, it } from 'vitest'
import { useSearch } from '../src/useSearch'

it('ignores late results and clears loading only for the current request', async () => {
  const pending = new Map<string, (values: string[]) => void>()
  const query = ref('first')
  let search!: ReturnType<typeof useSearch>
  const Host = defineComponent({
    setup() {
      search = useSearch(query, term => new Promise(resolve => pending.set(term, resolve)))
      return () => h('div')
    },
  })
  const wrapper = mount(Host)
  await nextTick()
  query.value = 'second'
  await nextTick()
  pending.get('second')!(['second result'])
  await Promise.resolve()
  await nextTick()
  expect(search.results.value).toEqual(['second result'])
  expect(search.loading.value).toBe(false)
  pending.get('first')!(['stale result'])
  await Promise.resolve()
  await nextTick()
  expect(search.results.value).toEqual(['second result'])
  expect(search.loading.value).toBe(false)
  query.value = 'third'
  await nextTick()
  wrapper.unmount()
  pending.get('third')!(['unmounted result'])
  await Promise.resolve()
  await nextTick()
  expect(search.results.value).toEqual(['second result'])
})
