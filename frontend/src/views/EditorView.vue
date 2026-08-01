<script setup>
import { ref, computed, nextTick } from 'vue'
import { useStore, refreshFrames, toast } from '../stores'
import { startJob } from '../jobs'
import api from '../api'

const store = useStore()
const frameIndex = ref(0)
const tolerance = ref(32)
const contiguous = ref(true)
const antiAlias = ref(true)
const fillColor = ref('#000000')
const operation = ref('delete')

const canvas = ref(null)
const selInfo = ref(null)
const maskOverlay = ref(null)   // Image 对象（选区蓝罩）
const hasSelection = ref(false)

const MAX_W = 640
const MAX_H = 420

async function loadFrame() {
  const idx = frameIndex.value
  if (idx == null || idx < 0 || idx >= store.frameCount) return toast('帧索引无效')
  await nextTick()
  const cv = canvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')

  const img = new Image()
  img.onload = () => {
    const scale = Math.min(MAX_W / img.naturalWidth, MAX_H / img.naturalHeight, 1)
    const dw = Math.round(img.naturalWidth * scale)
    const dh = Math.round(img.naturalHeight * scale)
    cv.width = dw
    cv.height = dh
    ctx.clearRect(0, 0, dw, dh)
    ctx.drawImage(img, 0, 0, dw, dh)
    hasSelection.value = false
    selInfo.value = null
    maskOverlay.value = null
  }
  img.onerror = () => toast('图像加载失败')
  img.src = api.frameImage(store.sessionId, idx, { type: 'preview', checker: 1, fit: 0, v: store.frameVersion })
}

async function onCanvasClick(e) {
  const cv = canvas.value
  if (!cv || !store.frameCount) return
  const rect = cv.getBoundingClientRect()
  const dispX = (e.clientX - rect.left)
  const dispY = (e.clientY - rect.top)
  const scaleX = cv.width / rect.width
  const scaleY = cv.height / rect.height
  const x = Math.round(dispX * scaleX)
  const y = Math.round(dispY * scaleY)

  try {
    const info = await api.wandSelect(store.sessionId, {
      frame_index: frameIndex.value,
      x, y,
      tolerance: tolerance.value,
      contiguous: contiguous.value,
      anti_alias: antiAlias.value,
    })
    selInfo.value = info
    const img = new Image()
    img.onload = () => {
      const ctx = cv.getContext('2d')
      ctx.drawImage(img, 0, 0, cv.width, cv.height)
      maskOverlay.value = img
      hasSelection.value = true
    }
    img.src = api.wandMask(store.sessionId, frameIndex.value)
    toast(`选区 ${info.bounds.width}x${info.bounds.height} 像素`)
  } catch (err) {
    toast(`选区失败: ${err.message}`)
  }
}

async function applyWand() {
  if (!hasSelection.value) return toast('请先在画布上点击创建选区')
  await startJob(() => api.wandApply(store.sessionId, {
    frame_index: frameIndex.value,
    operation: operation.value,
    fill_color: operation.value === 'fill' ? hexToRgba(fillColor.value) : undefined,
  }), {
    title: '魔棒编辑',
    onDone: async () => {
      await refreshFrames()
      toast('已应用，结果在「处理后」图层')
      loadFrame()
    },
  })
}

function hexToRgba(hex) {
  const h = hex.replace('#', '')
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 255]
}

async function clearSelection() {
  hasSelection.value = false
  selInfo.value = null
  maskOverlay.value = null
  loadFrame()
}
</script>

<template>
  <div class="grid2">
    <div>
      <div class="panel">
        <div class="section-title"><h2>魔棒选区编辑</h2></div>
        <div class="row">
          <div class="field inline"><label>帧索引</label>
            <input type="number" v-model.number="frameIndex" :min="0" :max="store.frameCount - 1" />
          </div>
          <button class="primary" @click="loadFrame">载入帧</button>
          <div class="field inline"><label>容差</label><input type="number" v-model.number="tolerance" :min="0" :max="255" /></div>
          <div class="field inline"><label>连续</label><input type="checkbox" v-model="contiguous" /></div>
          <div class="field inline"><label>抗锯齿</label><input type="checkbox" v-model="antiAlias" /></div>
        </div>
        <p class="hint">点击画布上的颜色区域创建选区（蓝色高亮）。</p>

        <div class="preview-box" style="cursor: crosshair; min-height: 300px">
          <canvas
            ref="canvas"
            @click="onCanvasClick"
            style="max-width:100%; max-height:420px; background:
              repeating-conic-gradient(#262626 0% 25%, #1c1c1c 0% 50%) 0 0 / 18px 18px"
          ></canvas>
          <span v-if="!store.frameCount" class="hint">暂无帧</span>
        </div>

        <div v-if="selInfo" class="mono" style="margin-top:8px">
          选区: {{ selInfo.bounds.width }} x {{ selInfo.bounds.height }} px（约 {{ (selInfo.area / (selInfo.bounds.width * selInfo.bounds.height || 1) * 100).toFixed(1) }}% 覆盖率）
        </div>
      </div>
    </div>

    <div>
      <div class="panel">
        <h3>选区操作</h3>
        <div class="row">
          <div class="field inline"><label>操作</label>
            <select v-model="operation">
              <option value="delete">删除选区内容</option>
              <option value="fill">填充颜色</option>
            </select>
          </div>
          <input v-if="operation === 'fill'" type="color" v-model="fillColor" />
        </div>
        <div class="row">
          <button class="primary" @click="applyWand">应用</button>
          <button @click="clearSelection">清除选区</button>
        </div>
        <p class="hint">应用后写入「处理后」图层（保留原始帧）。</p>
      </div>
    </div>
  </div>
</template>
