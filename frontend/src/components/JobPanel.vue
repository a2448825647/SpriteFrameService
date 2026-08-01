<script setup>
defineProps({
  jobs: { type: Array, required: true },
})
defineEmits(['cancel', 'close'])
</script>

<template>
  <div class="panel" style="position: fixed; right: 16px; bottom: 16px; width: 320px; z-index: 50; box-shadow: 0 6px 24px rgba(0,0,0,.5);">
    <div class="row2" style="align-items:center; margin-bottom:6px">
      <h3 style="margin:0">后台任务</h3>
      <span class="hint">{{ jobs.filter(j => j.status === 'running').length }} 个进行中</span>
      <button class="small" title="隐藏任务栏" @click="$emit('close')">✕</button>
    </div>
    <div class="job-list">
      <div v-for="j in jobs" :key="j.id" class="job-item" :class="{ error: j.status === 'error' }">
        <div class="row2">
          <span>{{ j.title }}</span>
          <span>{{ j.status === 'done' ? '完成' : j.status === 'error' ? '失败' : Math.round(j.progress) + '%' }}</span>
        </div>
        <div class="bar"><div :style="{ width: j.progress + '%' }"></div></div>
        <div class="row2"><span>{{ j.message }}</span>
          <button v-if="j.status === 'running'" class="small" @click="$emit('cancel', j.id)">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
