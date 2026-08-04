<script setup>
import { computed, ref } from 'vue'
import { Bell, Plus } from '@element-plus/icons-vue'
import TaskBoard from '../components/TaskBoard.vue'
import DashboardPanel from '../components/DashboardPanel.vue'
import NotesPanel from '../components/NotesPanel.vue'

// TaskBoard 通过 defineExpose 暴露 createTaskToday / enableNotifications /
// permissionState，hero 区的「新建待办 / 开启系统提醒」按钮直接委托给它。
const taskBoardRef = ref(null)

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 18) return '下午好'
  return '晚上好'
})
</script>

<template>
  <div class="workbench-page">
    <section class="workbench-hero">
      <div class="hero-copy">
        <div class="hero-eyebrow"><span /> WORKSPACE</div>
        <h1>{{ greeting }}，开始今天的工作吧</h1>
        <p>把重要事项放在这里，按节奏推进，不遗漏每一个时间节点。</p>
      </div>
      <div class="hero-actions">
        <el-button
          v-if="taskBoardRef?.permissionState === 'default'"
          :icon="Bell"
          plain
          @click="taskBoardRef?.enableNotifications()"
        >
          开启系统提醒
        </el-button>
        <el-button type="primary" :icon="Plus" @click="taskBoardRef?.createTaskToday()">
          新建待办
        </el-button>
      </div>
    </section>

    <!-- 三栏并排：待办事项 / 数据看板 / 随心记 同屏可见，无子选项卡 -->
    <div class="workbench-columns">
      <div class="workbench-col">
        <div class="col-head">
          <span class="section-kicker">TASKS</span>
          <h2>待办事项</h2>
        </div>
        <TaskBoard ref="taskBoardRef" />
      </div>

      <div class="workbench-col">
        <div class="col-head">
          <span class="section-kicker">INSIGHTS</span>
          <h2>数据看板</h2>
        </div>
        <DashboardPanel />
      </div>

      <div class="workbench-col">
        <div class="col-head">
          <span class="section-kicker">NOTES</span>
          <h2>随心记</h2>
        </div>
        <NotesPanel />
      </div>
    </div>
  </div>
</template>

<style scoped>
.workbench-page { --wb-indigo: #4f46e5; --wb-navy: #172554; max-width: 1560px; margin: 0 auto; }

/* hero（保留原样） */
.workbench-hero { position: relative; overflow: hidden; display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 132px; padding: 24px 30px; border: 1px solid rgba(99, 102, 241, .16); border-radius: 20px; background: radial-gradient(circle at 84% 15%, rgba(129, 140, 248, .28), transparent 26%), linear-gradient(120deg, #eef2ff 0%, #fff 54%, #f0f9ff 100%); box-shadow: 0 13px 34px rgba(30, 41, 59, .07); }
.workbench-hero::after { content: ''; position: absolute; right: 5%; bottom: -82px; width: 230px; height: 230px; border: 34px solid rgba(79, 70, 229, .06); border-radius: 50%; }
.hero-copy, .hero-actions { position: relative; z-index: 1; }
.hero-eyebrow, .section-kicker { color: #6366f1; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.hero-eyebrow { display: flex; align-items: center; gap: 8px; }
.hero-eyebrow span { width: 18px; height: 2px; border-radius: 2px; background: #6366f1; }
.hero-copy h1 { margin: 9px 0 8px; color: #172554; font-size: clamp(24px, 2.3vw, 34px); line-height: 1.2; letter-spacing: -.03em; }
.hero-copy p { margin: 0; color: #64748b; font-size: 14px; }
.hero-actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }

/* 三栏并排容器 */
.workbench-columns { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; margin-top: 18px; }
/* 每栏作为容器查询的上下文，使内部组件随列宽自适应（见 TaskBoard / DashboardPanel 的 @container 规则） */
.workbench-col { min-width: 0; display: flex; flex-direction: column; gap: 12px; container-type: inline-size; }
.col-head { display: flex; align-items: baseline; gap: 10px; padding: 0 2px; }
.col-head h2 { margin: 0; color: #172554; font-size: 18px; letter-spacing: -.02em; }

/* 响应式：宽屏三栏 → 中屏两栏 → 窄屏单列 */
@media (max-width: 1200px) {
  .workbench-columns { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); }
  .workbench-col:nth-child(3) { grid-column: 1 / -1; }
}
@media (max-width: 860px) {
  .workbench-columns { grid-template-columns: 1fr; }
  .workbench-col:nth-child(3) { grid-column: auto; }
  .workbench-hero { align-items: flex-start; flex-direction: column; padding: 22px; }
  .hero-actions { width: 100%; flex-wrap: wrap; }
  .hero-actions :deep(.el-button) { flex: 1; margin-left: 0; }
}
</style>
