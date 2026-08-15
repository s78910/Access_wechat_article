import { createApp } from 'vue'
import Antd from 'ant-design-vue'
import dayjs from 'dayjs'
import VxeUI from 'vxe-pc-ui'
import VxeUITable from 'vxe-table'
import App from './App.vue'
import 'ant-design-vue/dist/reset.css'
import 'dayjs/locale/zh-cn'
import 'vxe-pc-ui/lib/style.css'
import 'vxe-table/lib/style.css'
import './styles/pages.css'

// DatePicker 的月份和星期由 Day.js 提供，入口统一设置中文环境。
dayjs.locale('zh-cn')

const app = createApp(App)

// 完整注册 Ant Design Vue，后续页面可以按功能逐步替换现有控件。
app.use(Antd)
// Vben 的表格能力基于 Vxe 生态，这里按需注册基础组件，供页面使用表格、日期、分页等控件。
app.use(VxeUI)
app.use(VxeUITable)
app.mount('#app')
