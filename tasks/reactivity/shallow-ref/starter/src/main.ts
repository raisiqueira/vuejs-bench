import { createApp, h } from 'vue'
import { useCatalog } from './useCatalog'

const catalog = useCatalog()
createApp({ setup: () => () => h('output', catalog.catalog.value.items.length) }).mount('#app')
