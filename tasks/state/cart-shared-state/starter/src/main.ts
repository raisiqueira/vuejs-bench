import { createApp } from 'vue'
import App from './App.vue'
import { createAppRouter } from './router'
const app = createApp(App)
app.use(createAppRouter())
app.mount('#app')
