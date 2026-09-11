import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './assets/global.css'
import './assets/theme.css'
import 'highlight.js/styles/github-dark.css'  // 代码高亮样式
import 'katex/dist/katex.min.css'  // KaTeX 数学公式样式
import './utils/toast'
import i18n from './composables/useI18n'
import { getStoredToken, getCachedAuthProvider } from './api/auth'

// Import page components
import HomePage from './pages/HomePage.vue'
import ChatPage from './pages/ChatPage.vue'
import SkillsPage from './pages/SkillsPage.vue'
import SkillDetailPage from '@/pages/SkillDetailPage.vue'
import AgentsPage from './pages/AgentsPage.vue'
import TasksPage from './pages/TasksPage.vue'
import ApprovalsPage from './pages/ApprovalsPage.vue'
import StationOverviewPage from './pages/StationOverviewPage.vue'
import ModelOverviewPage from './pages/ModelOverviewPage.vue'
import ScoreOverviewPage from './pages/ScoreOverviewPage.vue'
import ScoreTracesPage from './pages/ScoreTracesPage.vue'
import ExperimentComparePage from './pages/ExperimentComparePage.vue'
import ProjectIntroPage from './pages/ProjectIntroPage.vue'
import LoginPage from './pages/LoginPage.vue'
import MainLayout from './pages/MainLayout.vue'
import SharePage from './pages/SharePage.vue';
import ShareLayout from './pages/ShareLayout.vue';

// Create router
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { 
      path: '/chat', 
      component: MainLayout,
      meta: { requiresAuth: true },
      children: [
        { 
          path: '', 
          component: HomePage, 
          alias: ['/', '/home'],
          meta: { requiresAuth: true }
        },
        { 
          path: ':sessionId', 
          component: ChatPage,
          meta: { requiresAuth: true }
        },
        { 
          path: 'skills', 
          component: SkillsPage,
          meta: { requiresAuth: true }
        },
        { 
          path: 'skills/:skillName', 
          component: SkillDetailPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'agents',
          component: AgentsPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'tasks',
          component: TasksPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'approvals',
          component: ApprovalsPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'overview',
          component: StationOverviewPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'intro',
          component: ProjectIntroPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'model-overview',
          component: ModelOverviewPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'scores',
          component: ScoreOverviewPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'score-traces',
          component: ScoreTracesPage,
          meta: { requiresAuth: true }
        },
        {
          path: 'experiments',
          component: ExperimentComparePage,
          meta: { requiresAuth: true }
        }
      ]
    },
    {
      path: '/share',
      component: ShareLayout,
      children: [
        {
          path: ':sessionId',
          component: SharePage,
        }
      ]
    },
    { 
      path: '/login', 
      component: LoginPage
    }
  ]
})

// Global route guard
router.beforeEach(async (to, _, next) => {
  const requiresAuth = to.matched.some((record: any) => record.meta?.requiresAuth)
  const hasToken = !!getStoredToken()
  
  if (requiresAuth) {
    const authProvider = await getCachedAuthProvider()
    
    if (authProvider === 'none') {
      next()
      return
    }
    
    if (!hasToken) {
      next({
        path: '/login',
        query: { redirect: to.fullPath }
      })
      return
    }
  }
  
  if (to.path === '/login' && hasToken) {
    next('/')
  } else {
    next()
  }
})

const app = createApp(App)

app.use(router)
app.use(i18n)
app.mount('#app')
