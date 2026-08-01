<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useStore, refreshFrames, refreshSession, toast } from '../stores'
import { startJob } from '../jobs'
import api from '../api'

const store = useStore()
const dragOver = ref(false)
const uploading = ref(false)
const fileInput = ref(null)

const startTime = ref(0)
const endTime = ref(10)
const fps = ref(10)
const videoEl = ref(null)

const videoUrl = computed(() =>
  store.sessionId ? `/api/sessions/${store.sessionId}/video` : ''
)

const estimate = computed(() => {
  const dur = Math.max(0, endTime.value - startTime.value)
  return Math.max(0, Math.round(dur * fps.value))
})

function onFile(file) {
  if (!file) return
  uploadFile(file)
}

async function uploadFile(file) {
  if (!store.sessionId) return
  uploading.value = true
  try {
    const res = await api.uploadVideo(store.sessionId, file)
    store.videoInfo = res.video_info
    // 帧率默认取源视频帧率（上限 60）
    const srcFps = store.videoInfo.fps || 10
    fps.value = Math.min(60, Math.max(0.1, srcFps))
    endTime.value = store.videoInfo.duration
    toast('视频上传成功')
    await refreshSession()
    await nextTick()
    if (videoEl.value) videoEl.value.load()
  } catch (e) {
    toast(`上传失败: ${e.message}`)
  } finally {
    uploading.value = false
    // 重置文件输入，允许重复选择同一文件
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function extract() {
  if (!store.videoInfo) return toast('请先上传视频')
  if (startTime.value >= endTime.value) return toast('开始时间必须小于结束时间')
  await startJob(
    () => api.extract(store.sessionId, {
      start_time: startTime.value,
      end_time: endTime.value,
      fps: fps.value,
    }),
    {
      title: `抽帧 (${fps.value} fps)`,
      onDone: async () => {
        await refreshFrames()
      },
    },
  )
}

onMounted(async () => {
  await refreshSession()
  if (store.videoInfo) {
    endTime.value = store.videoInfo.duration
    const srcFps = store.videoInfo.fps || 10
    fps.value = Math.min(60, Math.max(0.1, srcFps))
  }
})
</script>

<template>
  <div class="panel">
    <div class="section-title"><h2>1. 上传视频</h2></div>

    <div
      class="upload-drop"
      :class="{ dragover: dragOver }"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="dragOver = false; onFile($event.dataTransfer.files[0])"
      @click="fileInput.click()"
    >
      <div v-if="!uploading">点击或拖拽视频文件到此处<br><span class="hint">支持 mp4 / mov / avi / mkv / webm 等（浏览器可播放的编码可直接预览）</span></div>
      <div v-else>上传中...</div>
      <input ref="fileInput" type="file" accept="video/*" style="display:none" @change="e => onFile(e.target.files[0])" />
    </div>

    <div v-if="store.videoInfo" style="margin-top: 14px">
      <div class="grid2">
        <div>
          <div class="preview-box" style="min-height: 260px">
            <video
              v-if="videoUrl" ref="videoEl" :src="videoUrl"
              controls style="max-width:100%; max-height:420px"
            ></video>
          </div>
        </div>
        <div>
          <h3 style="margin-top:0">视频信息</h3>
          <table class="tbl">
            <tr><th>分辨率</th><td>{{ store.videoInfo.width }} x {{ store.videoInfo.height }}</td></tr>
            <tr><th>帧率</th><td>{{ store.videoInfo.fps.toFixed(2) }} fps</td></tr>
            <tr><th>总帧数</th><td>{{ store.videoInfo.frame_count }}</td></tr>
            <tr><th>时长</th><td>{{ store.videoInfo.duration.toFixed(2) }} s</td></tr>
            <tr><th>编码</th><td>{{ store.videoInfo.codec }}</td></tr>
          </table>
        </div>
      </div>

      <h3 style="margin-top:16px">2. 抽帧设置</h3>
      <div class="row">
        <div class="field inline"><label>开始(s)</label><input type="number" v-model.number="startTime" :min="0" :max="store.videoInfo.duration" step="0.1" /></div>
        <div class="field inline"><label>结束(s)</label><input type="number" v-model.number="endTime" :min="0" :max="store.videoInfo.duration" step="0.1" /></div>
        <div class="field inline"><label>FPS</label><input type="number" v-model.number="fps" :min="0.1" :max="60" step="0.5" /></div>
        <button class="small" @click="startTime = 0; endTime = store.videoInfo.duration">全部</button>
        <button class="small" @click="startTime = 0; endTime = store.videoInfo.duration / 2">前50%</button>
        <button class="small" @click="startTime = store.videoInfo.duration / 2; endTime = store.videoInfo.duration">后50%</button>
        <span class="hint">预计抽帧: {{ estimate }} 帧</span>
      </div>
      <div class="row">
        <button class="primary" @click="extract">提取帧</button>
      </div>    </div>
  </div>
</template>
