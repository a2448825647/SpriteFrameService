<script setup>
import { ref, computed, onMounted } from 'vue'
import { useStore, refreshFrames, toast } from '../stores'
import { startJob } from '../jobs'
import api from '../api'

const store = useStore()
const entries = ref([])
const memory = ref('')
const busy = ref(false)

async function load() {
  try {
    const r = await api.history(store.sessionId)
    entries.value = r.entries
    memory.value = r.memory || ''
  } catch {
    entries.value = []
  }
}

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function revertTo(stepId) {
  const isInit = stepId === 0
  if (!confirm(isInit ? '回退到初始状态（撤销全部修改）？' : '回退到该步骤完成后的状态（撤销之后的操作）？')) return
  busy.value = true
  await startJob(() => api.revert(store.sessionId, stepId), {
    title: '历史回退',
    onDone: async (r) => {
      await refreshFrames()
      await load()
      toast(r.count ? `已回退，影响 ${r.count} 帧` : '该步骤没有可回退的修改')
    },
  })
  busy.value = false
}

// 撤销上一步：回退到倒数第二条记录的位置（仅 1 条时回退到初始）
function undoLast() {
  if (!entries.value.length) return
  const target = entries.value.length >= 2 ? entries.value[1].step_id : 0
  revertTo(target)
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div class="section-title"><h2>历史回退</h2></div>
    <p class="desc">对帧的修改（抠图/描边/缩放/裁剪/边缘优化/增强/魔棒编辑）会记录历史快照，可回退到任意步骤。最多保留最近 10 步。</p>

    <div class="row">
      <button class="primary" :disabled="busy || !entries.length" @click="undoLast">撤销上一步</button>
      <button :disabled="busy || !entries.length" @click="revertTo(0)">回退到初始状态</button>
      <button class="small" @click="load">刷新</button>
      <span v-if="memory" class="hint">占用内存：{{ memory }}</span>
    </div>

    <div v-if="entries.length" class="history-list">
      <div v-for="(e, i) in entries" :key="e.step_id" class="history-item">
        <div class="row2">
          <span class="mono">#{{ e.step_id }} · {{ e.operation_name }}</span>
          <span class="hint">{{ fmtTime(e.timestamp) }} · {{ e.affected_count }} 帧</span>
        </div>
        <div class="history-desc">{{ e.description }}</div>
        <div class="row" style="margin-top:4px">
          <button class="small" :disabled="busy || i === 0" @click="revertTo(e.step_id)">回退到此处</button>
          <span v-if="i === 0" class="hint">（最新步骤，无需回退）</span>
        </div>
      </div>
    </div>
    <p v-else class="hint">暂无历史记录。对帧执行处理操作后会自动生成快照。</p>
  </div>
</template>

<style scoped>
.history-list { display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow-y: auto; }
.history-item {
  background: var(--bg-input); border: 1px solid var(--border); border-radius: 4px; padding: 8px 12px;
}
.history-desc { color: var(--text-dim); font-size: 12px; margin-top: 2px; }
</style>
