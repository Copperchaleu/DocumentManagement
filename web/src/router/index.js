import { createRouter, createWebHashHistory } from 'vue-router'
import AppLayout from '../layouts/AppLayout.vue'

const routes = [
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/compose' },
      {
        path: 'compose',
        name: 'compose',
        component: () => import('../views/ComposeView.vue'),
        meta: { title: '粘贴保存' },
      },
      {
        path: 'workbench',
        name: 'workbench',
        component: () => import('../views/WorkbenchView.vue'),
        meta: { title: '工作面板' },
      },
      {
        path: 'projects',
        name: 'projects',
        component: () => import('../views/ProjectsView.vue'),
        meta: { title: '项目列表' },
      },
      {
        path: 'period',
        name: 'period',
        component: () => import('../views/PeriodView.vue'),
        meta: { title: '周期文件' },
      },
      {
        path: 'categories',
        name: 'categories',
        component: () => import('../views/CategoriesView.vue'),
        meta: { title: '分类管理' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('../views/SettingsView.vue'),
        meta: { title: '系统设置' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
