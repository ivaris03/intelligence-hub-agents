import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { settingsApi } from './lib/api'
import router from './router'
import './styles/main.css'

void settingsApi
  .get()
  .then((settings) => {
    document.documentElement.dataset.theme = settings.appearance
  })
  .catch(() => undefined)

createApp(App).use(createPinia()).use(router).mount('#app')
