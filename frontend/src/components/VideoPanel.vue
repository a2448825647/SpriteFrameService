<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { useStore, refreshFrames, toast } from '../stores'
import { startJob } from '../jobs'
import api from '../api'

const store = useStore()

// ---- 动画预览（循环切换选中帧） ----
const animFrame = ref(0)
const animFps = ref(10)
const animRunning = ref(false)
let timer = null

const animFrames = computed(() => {
  const idx = store.frames.filter((f) => f.is_selected).map((f) => f.index)
  return idx.length ? idx : store.frames.map((f) => f.index)
})

const animUrl = computed(() =>
  store.sessionId && animFrames.value.length && animFrames.value[animFrame.value] != null
    ? api.frameImage(store.sessionId, animFrames.value[animFrame.value], { fit: 360, v: store.frameVersion })
    : ''
)

function startAnim() {
  stopAnim()
  animFrame.value = 0
  animRunning.value = true
  timer = setInterval(() => {
    animFrame.value = (animFrame.value + 1) % Math.max(1, animFrames.value.length)
  }, 1000 / animFps.value)
}
function stopAnim() {
  animRunning.value = false
  if (timer) { clearInterval(timer); timer = null }
}
onBeforeUnmount(stopAnim)

// ---- 循环过渡预览 ----
const loopGifUrl = ref(null)
const loopBusy = ref(false)

function onLoopEnabled(v) {
  store.loopTransition.enabled = v
  if (v) {
    genLoopPreview()
  } else {
    loopGifUrl.value = null
  }
}
function onLoopParamChange() {
  if (store.loopTransition.enabled) genLoopPreview()
}

async function genLoopPreview() {
  if (animFrames.value.length < 2) return toast('至少需要 2 帧才能循环过渡')
  loopBusy.value = true
  await startJob(() => api.loopTransition(store.sessionId, {
    indices: animFrames.value,
    count: store.loopTransition.count,
    mode: store.loopTransition.mode,
    fps: animFps.value,
  }), {
    title: '循环过渡预览',
    onDone: (r) => {
      if (r && r.gif) loopGifUrl.value = r.gif
    },
  })
  loopBusy.value = false
}

// ---- 首尾补帧 ----
const supplementCount = ref(3)
const supplementBusy = ref(false)

async function runSupplement() {
  if (animFrames.value.length < 2) return toast('至少需要 2 帧才能补帧')
  supplementBusy.value = true
  await startJob(() => api.supplement(store.sessionId, {
    indices: animFrames.value,
    num_frames: supplementCount.value,
  }), {
    title: '首尾补帧',
    onDone: async (r) => {
      await refreshFrames()
      if (r) toast(`补帧完成，新增 ${r.added} 帧`)
    },
  })
  supplementBusy.value = false
}
</script>

<template>
  <div class="video-panel">
    <!-- 动画预览 -->
    <div class="panel" style="padding:10px">
      <h3 style="margin:0 0 8px">动画预览</h3>

      <div class="preview-box" style="min-height:160px">
        <!-- 循环过渡预览 GIF -->
        <img v-if="loopGifUrl" :src="loopGifUrl" style="max-width:100%; max-height:260px; object-fit:contain" />
        <!-- 普通帧循环播放 -->
        <img v-else-if="animRunning && animUrl" :src="animUrl" style="max-width:100%; max-height:260px; object-fit:contain" />
        <span v-else class="hint">点击「播放」预览选中帧动画</span>
      </div>

      <div class="row" style="margin-top:8px">
        <button class="small" v-if="!animRunning" @click="startAnim">▶ 播放</button>
        <button class="small" v-else @click="stopAnim">⏹ 停止</button>
        <div class="field inline"><label>fps</label><input type="number" v-model.number="animFps" :min="1" :max="30" /></div>
        <button class="small" v-if="loopGifUrl" @click="loopGifUrl = null">清除预览</button>
      </div>
    </div>

    <!-- 循环过渡 + 首尾补帧 -->
    <div class="panel" style="padding:10px">
      <h3 style="margin:0 0 8px">循环处理</h3>

      <div class="row">
        <div class="field inline"><label>循环过渡</label><input type="checkbox" :checked="store.loopTransition.enabled" @change="e => onLoopEnabled(e.target.checked)" /></div>
        <div class="field inline"><label>帧数</label><input type="number" v-model.number="store.loopTransition.count" :min="1" :max="30" @change="onLoopParamChange" /></div>
        <div class="field inline"><label>模式</label>
          <select v-model="store.loopTransition.mode" @change="onLoopParamChange">
            <option value="blend">像素混合</option>
            <option value="align">轮廓对齐</option>
          </select>
        </div>
        <button class="small" :disabled="loopBusy" @click="genLoopPreview">生成预览</button>
      </div>
      <p class="hint" style="margin:4px 0 0">开启后，导出精灵图/GIF 时将自动应用循环过渡，使首尾无缝衔接。</p>

      <div class="row" style="margin-top:10px; border-top:1px solid var(--border); padding-top:10px">
        <span class="hint">首尾补帧：</span>
        <div class="field inline" v-for="n in [1,2,3,4,5,6,7]" :key="n">
          <label><input type="radio" :value="n" v-model="supplementCount" /> {{ n }}</label>
        </div>
        <button class="small" :disabled="supplementBusy" @click="runSupplement">开始补帧</button>
      </div>
      <p class="hint" style="margin:4px 0 0">在选中帧的「尾帧→首帧」之间生成中间帧并追加到帧管理（标签：补），⚠️ 建议在抠图前补帧。</p>
    </div>
  </div>
</template>

<style scoped>
.video-panel { padding: 12px; }
</style>
