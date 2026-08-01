<script setup>
import { ref } from 'vue'
import { useStore, refreshFrames, toast } from '../stores'
import api from '../api'

const props = defineProps({
  selectable: { type: Boolean, default: true },
  fit: { type: Number, default: 0 },        // 缩略图最大边长
})
const emit = defineEmits(['select', 'click'])

const store = useStore()

// 上次点击的帧索引（Shift 批量选中的锚点）
const lastClick = ref(null)

function imgUrl(frame, type = 'preview') {
  return api.frameImage(store.sessionId, frame.index, { type, fit: props.fit || 160, v: store.frameVersion })
}

async function click(frame, e) {
  if (!props.selectable) return
  const cur = frame.index
  const existing = store.frames.filter((f) => f.is_selected).map((f) => f.index)

  let indices
  if (e.shiftKey && lastClick.value != null) {
    // Shift + 点击：批量选中/取消 [锚点..当前] 区间
    const [a, b] = [Math.min(lastClick.value, cur), Math.max(lastClick.value, cur)]
    const range = store.frames.filter((f) => f.index >= a && f.index <= b).map((f) => f.index)
    if (!frame.is_selected) {
      // 当前帧未选中 → 范围内全部选中（保留原有选中）
      indices = [...new Set([...existing, ...range])]
    } else {
      // 当前帧已选中 → 范围内全部取消（保留范围外选中）
      indices = existing.filter((i) => i < a || i > b)
    }
  } else {
    // 普通点击：切换单个帧
    if (frame.is_selected) {
      indices = existing.filter((i) => i !== cur)
    } else {
      indices = [...existing, cur]
    }
  }
  lastClick.value = cur
  await api.selection(store.sessionId, { mode: 'set', indices })
  await refreshFrames()
  emit('select', indices)
}

function onClick(frame, e) {
  if (!props.selectable) {
    emit('click', frame)
    return
  }
  click(frame, e)
}
</script>

<template>
  <div class="gallery">
    <div
      v-for="f in store.frames" :key="f.id"
      class="frame-item" :class="{ selected: f.is_selected }"
      @click="onClick(f, $event)"
      :title="`帧 #${f.index}  t=${f.timestamp.toFixed(3)}s${f.tag ? '  [' + f.tag + ']' : ''}`"
    >
      <img class="thumb" :src="imgUrl(f)" :alt="`frame ${f.index}`" loading="lazy" />
      <div class="idx">#{{ f.index }}</div>
      <div class="badges">
        <span v-if="f.tag" class="badge" style="background:#e91e63">{{ f.tag }}</span>
        <span v-if="f.has_processed" class="badge proc">处理</span>
        <span v-if="f.analysis.pose" class="badge pose">姿势</span>
        <span v-if="f.analysis.contour" class="badge" style="background:#ffb300">轮廓</span>
        <span v-if="f.analysis.image" class="badge" style="background:#7c4dff">特征</span>
        <span v-if="f.analysis.regional" class="badge" style="background:#00bfa5">SSIM</span>
      </div>
      <div v-if="f.is_selected" class="check">✓</div>
    </div>
    <div v-if="!store.frames.length" class="hint" style="grid-column:1/-1; text-align:center; padding:30px">
      暂无帧，请先在「视频抽帧」中提取
    </div>
  </div>
</template>
