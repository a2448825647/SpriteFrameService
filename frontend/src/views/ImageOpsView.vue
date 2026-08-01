<script setup>
import { ref, computed } from 'vue'
import { useStore, refreshFrames, toast } from '../stores'
import { startJob } from '../jobs'
import api from '../api'

const store = useStore()

const scaleMode = ref('percent')
const percent = ref(50)
const width = ref(512)
const height = ref(512)
const algorithm = ref('lanczos')

const cropMargins = ref({ top: 0, bottom: 0, left: 0, right: 0 })
const edgeErode = ref(1)

const esrganModel = ref('realesrgan-x4plus')
const esrganTile = ref(0)

const selected = computed(() =>
  store.frames.filter((f) => f.is_selected).map((f) => f.index)
)

const esrganModels = computed(() => store.capabilities?.realesrgan || [])
const esrganAvailable = computed(() =>
  store.capabilities?.realesrgan_info?.available
)

async function runScale() {
  const params = { mode: scaleMode.value, algorithm: algorithm.value }
  if (selected.value.length) params.indices = selected.value
  if (scaleMode.value === 'percent') params.percent = percent.value
  else { params.width = width.value; params.height = height.value }
  await startJob(() => api.scale(store.sessionId, params), {
    title: '批量缩放',
    onDone: async (r) => {
      await refreshFrames()
      toast(`缩放完成：${r.from} → ${r.to}`)
    },
  })
}

async function runCrop() {
  const params = { ...cropMargins.value }
  if (selected.value.length) params.indices = selected.value
  await startJob(() => api.crop(store.sessionId, params), {
    title: '空白裁剪',
    onDone: async (r) => {
      await refreshFrames()
      toast(r.processed ? `裁剪完成：${r.size}` : r.message)
    },
  })
}

async function runEdges() {
  const params = { erode: edgeErode.value }
  if (selected.value.length) params.indices = selected.value
  await startJob(() => api.optimizeEdges(store.sessionId, params), {
    title: '边缘优化',
    onDone: async (r) => {
      await refreshFrames()
      toast(`边缘优化完成：${r.processed} 帧`)
    },
  })
}

async function runEnhance() {
  const params = { model: esrganModel.value, tile: esrganTile.value }
  if (selected.value.length) params.indices = selected.value
  await startJob(() => api.enhance(store.sessionId, params), {
    title: '图像增强',
    onDone: async (r) => {
      await refreshFrames()
      toast(`增强完成：${r.processed} 帧`)
    },
  })
}
</script>

<template>
  <div class="grid2">
    <div>
      <div class="panel">
        <h3>批量缩放</h3>
        <div class="row">
          <div class="field inline"><label>方式</label>
            <select v-model="scaleMode">
              <option value="percent">按比例</option>
              <option value="size">固定尺寸</option>
            </select>
          </div>
          <template v-if="scaleMode === 'percent'">
            <div class="field inline"><label>%</label><input type="number" v-model.number="percent" :min="1" :max="400" /></div>
          </template>
          <template v-else>
            <div class="field inline"><label>宽</label><input type="number" v-model.number="width" :min="1" /></div>
            <div class="field inline"><label>高</label><input type="number" v-model.number="height" :min="1" /></div>
          </template>
          <div class="field inline"><label>算法</label>
            <select v-model="algorithm">
              <option v-for="a in store.capabilities?.scale_algorithms || []" :key="a" :value="a">{{ a }}</option>
            </select>
          </div>
        </div>
        <button class="primary" @click="runScale">缩放选中帧</button>
      </div>

      <div class="panel">
        <h3>空白裁剪</h3>
        <p class="desc">计算所有选中帧的联合内容边界，统一裁剪多余空白（保留边距）。</p>
        <div class="row">
          <div class="field inline"><label>上</label><input type="number" v-model.number="cropMargins.top" :min="0" :max="100" /></div>
          <div class="field inline"><label>下</label><input type="number" v-model.number="cropMargins.bottom" :min="0" :max="100" /></div>
          <div class="field inline"><label>左</label><input type="number" v-model.number="cropMargins.left" :min="0" :max="100" /></div>
          <div class="field inline"><label>右</label><input type="number" v-model.number="cropMargins.right" :min="0" :max="100" /></div>
        </div>
        <button class="primary" @click="runCrop">裁剪选中帧</button>
      </div>

      <div class="panel">
        <h3>边缘优化</h3>
        <p class="desc">对已抠图帧的 alpha 通道做腐蚀收缩，去除毛刺。</p>
        <div class="row">
          <div class="field inline"><label>收缩像素</label><input type="number" v-model.number="edgeErode" :min="1" :max="20" /></div>
          <button class="primary" @click="runEdges">优化选中帧</button>
        </div>
      </div>
    </div>

    <div>
      <div class="panel">
        <h3>RealESRGAN 图像增强</h3>
        <p class="desc">使用 Real-ESRGAN 对帧做超分辨率修复。</p>
        <template v-if="esrganAvailable">
          <div class="row">
            <div class="field inline"><label>模型</label>
              <select v-model="esrganModel">
                <option v-for="m in esrganModels" :key="m.name" :value="m.name" :disabled="!m.installed">
                  {{ m.display_name }} {{ m.installed ? '' : '(未安装)' }}
                </option>
              </select>
            </div>
            <div class="field inline"><label>分块</label><input type="number" v-model.number="esrganTile" :min="0" :max="512" title="0=不分块" /></div>
          </div>
          <button class="primary" @click="runEnhance">增强选中帧</button>
        </template>
        <p v-else class="hint" style="color: var(--err)">
          Real-ESRGAN 不可用：需要在 models/realesrgan/ 放置可执行文件与模型（Linux 使用 realesrgan-ncnn-vulkan）。
        </p>
      </div>

      <div class="panel">
        <h3>说明</h3>
        <ul class="hint">
          <li>以上操作均对「选中帧」执行；未选定时对全部帧执行。</li>
          <li>结果写入「处理后」图层，可通过右上角「历史回退」撤销。</li>
          <li>建议顺序：抠图 → 边缘优化 → 裁剪 → 缩放 → 增强。</li>
        </ul>
      </div>
    </div>
  </div>
</template>
