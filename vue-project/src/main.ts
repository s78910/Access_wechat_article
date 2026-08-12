import { createApp } from 'vue'
import VxeUI from 'vxe-pc-ui'
import VxeUITable from 'vxe-table'
import App from './App.vue'
import 'vxe-pc-ui/lib/style.css'
import 'vxe-table/lib/style.css'
import './styles/pages.css'

const app = createApp(App)

// Vben 的表格能力基于 Vxe 生态，这里按需注册基础组件，供页面使用表格、日期、分页等控件。
app.use(VxeUI)
app.use(VxeUITable)
app.mount('#app')
