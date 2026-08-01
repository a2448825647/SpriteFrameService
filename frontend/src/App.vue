<script setup>
import { ref, watch, onMounted } from 'vue'
import { useStore, initSession, loadCapabilities, toast } from './stores'
import { useJobs, cancelJob } from './jobs'
import { currentTab } from './nav'
import VideoView from './views/VideoView.vue'
import AnalysisView from './views/AnalysisView.vue'
import BackgroundView from './views/BackgroundView.vue'
import ImageOpsView from './views/ImageOpsView.vue'
import EditorView from './views/EditorView.vue'
import ExportView from './views/ExportView.vue'
import HistoryView from './views/HistoryView.vue'
import JobPanel from './components/JobPanel.vue'
import FrameBrowser from './components/FrameBrowser.vue'
import VideoPanel from './components/VideoPanel.vue'

const store = useStore()
const jobs = useJobs()
const tab = currentTab
const ready = ref(false)
const err = ref('')
const jobsVisible = ref(true)   // 后台任务栏是否显示

// 有新任务启动时自动展开任务栏
watch(() => jobs.items.length, (n, old) => {
  if (n > old) jobsVisible.value = true
})

const runningCount = () => jobs.items.filter((j) => j.status === 'running').length

const tabs = [
  { key: 'video', label: '视频抽帧' },
  { key: 'analysis', label: '动作分析' },
  { key: 'background', label: '背景处理' },
  { key: 'image', label: '图像处理' },
  { key: 'editor', label: '魔棒编辑' },
  { key: 'export', label: '导出' },
  { key: 'history', label: '历史回退' },
]

const views = {
  video: VideoView,
  analysis: AnalysisView,
  background: BackgroundView,
  image: ImageOpsView,
  editor: EditorView,
  export: ExportView,
  history: HistoryView,
}

onMounted(async () => {
  try {
    await loadCapabilities()
    await initSession()
    ready.value = true
  } catch (e) {
    err.value = `无法连接后端服务: ${e.message}`
  }
})

function fmtDuration(sec) {
  if (sec == null) return ''
  const m = Math.floor(sec / 60)
  const s = (sec % 60).toFixed(2)
  return m > 0 ? `${m}m${s.padStart(5, '0')}s` : `${s}s`
}

async function newSession() {
  const ok = confirm('新建项目会丢弃当前会话（含已上传视频与帧），确定继续？')
  if (!ok) return
  await initSession()
  toast('已新建会话')
}
</script>

<template>
  <div class="layout" v-if="ready">
    <aside class="sidebar">
      <div class="brand">精灵帧工作室<small>SpriteFrameService</small></div>
      <button
        v-for="t in tabs" :key="t.key"
        class="tab" :class="{ active: tab === t.key }"
        @click="tab = t.key"
      >{{ t.label }}</button>
      <div class="spacer"></div>
      <button class="tab" @click="newSession">新建项目</button>
    </aside>

    <div class="main">
      <div class="topbar">
        <span class="session-info">会话: {{ store.sessionId?.slice(0, 8) }}</span>
        <span v-if="store.videoInfo" class="session-info">
          {{ store.videoInfo.width }}x{{ store.videoInfo.height }} · {{ fmtDuration(store.videoInfo.duration) }} · {{ store.frameCount }} 帧
        </span>
        <span class="spacer"></span>
        <span v-if="store.capabilities?.platform" class="session-info">
          {{ store.capabilities.platform.os }}
          <span v-if="store.capabilities.platform.gpu_available" style="color: var(--ok)">· GPU</span>
        </span>
      </div>

      <div class="main-body">
        <!-- 左侧工作区 -->
        <div class="content-area">
          <div class="content">
            <component :is="views[tab]" />
          </div>
        </div>

        <!-- 右侧视频预览（除视频抽帧外常驻） -->
        <div v-if="tab !== 'video'" class="video-panel-wrap">
          <VideoPanel />
        </div>
      </div>

      <!-- 底部帧管理（类似内容浏览器，可折叠/弹出） -->
      <FrameBrowser />
    </div>
  </div>

  <div v-else-if="err" style="display:flex;height:100%;align-items:center;justify-content:center;">
    <div style="text-align:center;color:var(--err)">
      <h2>无法连接后端服务</h2>
      <p>{{ err }}</p>
      <p class="hint">请确认后端已启动：<code>python backend/run.py</code></p>
    </div>
  </div>

  <div v-else style="display:flex;height:100%;align-items:center;justify-content:center;color:var(--text-dim)">
    正在连接后端服务...
  </div>

  <JobPanel v-if="jobsVisible && jobs.items.length" :jobs="jobs.items" @cancel="cancelJob" @close="jobsVisible = false" />
  <button v-if="!jobsVisible && jobs.items.length" class="job-toggle" @click="jobsVisible = true">
    后台任务 <span v-if="runningCount()">({{ runningCount() }} 进行中)</span>
  </button>

  <div v-if="store.toast" class="toast">{{ store.toast }}</div>
</template>

<style scoped>
.main-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.content {
  flex: 1;
  overflow: auto;
  padding: 16px;
}
.video-panel-wrap {
  width: 42%;
  min-width: 320px;
  border-left: 1px solid var(--border);
  overflow-y: auto;
  background: var(--bg-panel);
}
</style>
