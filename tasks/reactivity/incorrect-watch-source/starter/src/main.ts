import { createApp, h } from 'vue'
import { useWatchedCounter } from './useWatchedCounter'

const counter = useWatchedCounter()
createApp({ setup: () => () => h('output', counter.events) }).mount('#app')
