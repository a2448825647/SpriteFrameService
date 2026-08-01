<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useStore, toast } from '../stores'
import { startJob } from '../jobs'
import api from '../api'

const store = useStore()
const format = ref('sprite_sheet')
const outputName = ref('sprite')

const sprite = reactive({
  layout: 'grid', columns: null, padding: 0,
  frame_width: null, frame_height: null,
  generate_json: true, resample_filter: 'lanczos',
  bg_color: '#00000000',
})
const gif = reactive({ fps: 10, loop: 0, optimize: true, frame_width: 256, frame_height: 256, resample_filter: 'lanczos' })
const webp = reactive({ quality: 80, frame_width: null, frame_height: null })
const godot = reactive({ animation_name: 'default', fps: 10, loop: true, export_individual_frames: true, frame_width: null, frame_height: null })
const pngquant = reactive({ enabled: false, quality_min: 60, quality_max: 80 })

const exports = ref([])
const selected = computed(() => store.frames.filter((f) => f.is_selected).map((f) => f.index))

const formats = [
  { key: 'sprite_sheet', name: 'PNG 精灵图 + JSON' },
  { key: 'gif', name: 'GIF 动画' },
  { key: 'frames', name: '单独帧 PNG' },
  { key: 'webp', name: 'WebP' },
  { key: 'godot', name: 'Godot SpriteFrames' },
]

function hexToRgba(hex) {
  const h = hex.replace('#', '')
  if (h.length === 8) {
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), parseInt(h.slice(6, 8), 16)]
  }
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 255]
}

function buildConfig() {
  const common = {
    output_name: outputName.value,
    pngquant_config: { enabled: pngquant.enabled, quality_min: pngquant.quality_min, quality_max: pngquant.quality_max },
    loop_transition: {
      enabled: store.loopTransition.enabled,
      count: store.loopTransition.count,
      mode: store.loopTransition.mode,
    },
  }
  if (format.value === 'sprite_sheet') {
    return {
      format: 'sprite_sheet',
      ...common,
      sprite_config: {
        layout: sprite.layout, columns: sprite.columns, padding: sprite.padding,
        frame_width: sprite.frame_width, frame_height: sprite.frame_height,
        generate_json: sprite.generate_json, resample_filter: sprite.resample_filter,
        background_color: hexToRgba(sprite.bg_color),
      },
    }
  }
  if (format.value === 'gif') {
    return {
      format: 'gif', ...common,
      gif_config: {
        fps: gif.fps, loop: gif.loop, optimize: gif.optimize,
        frame_width: gif.frame_width, frame_height: gif.frame_height,
        resample_filter: gif.resample_filter,
      },
    }
  }
  if (format.value === 'frames') {
    return { format: 'frames', ...common }
  }
  if (format.value === 'webp') {
    // 默认精灵图 WebP；若设置 frame 尺寸则导出单独 WebP 帧
    const asSpriteSheet = webpIsSheet.value
    return {
      format: 'webp', ...common,
      sprite_config: asSpriteSheet
        ? {
            layout: sprite.layout, columns: sprite.columns, padding: sprite.padding,
            frame_width: webp.frame_width, frame_height: webp.frame_height,
            generate_json: false, resample_filter: sprite.resample_filter,
            background_color: hexToRgba(sprite.bg_color),
          }
        : null,
      webp_config: { quality: webp.quality, frame_width: webp.frame_width, frame_height: webp.frame_height },
    }
  }
  return {
    format: 'godot', ...common,
    godot_config: {
      animation_name: godot.animation_name, fps: godot.fps, loop: godot.loop,
      export_individual_frames: godot.export_individual_frames,
      frame_width: godot.frame_width, frame_height: godot.frame_height,
    },
  }
}

const webpIsSheet = ref(true)

async function doExport() {
  if (!store.frames.length) return toast('请先抽帧')
  const config = buildConfig()
  await startJob(() => api.export(store.sessionId, { config, indices: selected.value.length ? selected.value : undefined }), {
    title: `导出 (${format.value})`,
    onDone: async () => {
      toast('导出完成')
      await refreshExports()
    },
  })
}

async function refreshExports() {
  try {
    exports.value = await api.exports(store.sessionId)
  } catch { /* ignore */ }
}

function fmtSize(b) {
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / (1024 * 1024)).toFixed(2) + ' MB'
}

function downloadExport(ex) {
  window.open(api.exportDownload(store.sessionId, ex.name), '_blank')
}

onMounted(refreshExports)
</script>

<template>
  <div class="grid2">
    <div>
      <div class="panel">
        <div class="section-title"><h2>导出</h2></div>
        <div class="row">
          <div class="field inline"><label>格式</label>
            <select v-model="format">
              <option v-for="f in formats" :key="f.key" :value="f.key">{{ f.name }}</option>
            </select>
          </div>
          <div class="field inline"><label>文件名</label><input v-model="outputName" /></div>
          <span class="hint">将导出 {{ selected.length || store.frameCount }} 帧（选中帧）</span>
        </div>

        <!-- 精灵图配置 -->
        <div v-if="format === 'sprite_sheet' || (format === 'webp' && webpIsSheet)" class="row" style="border-top:1px solid var(--border); padding-top:10px">
          <div class="field inline"><label>布局</label>
            <select v-model="sprite.layout">
              <option value="grid">网格</option>
              <option value="horizontal">水平</option>
              <option value="vertical">垂直</option>
            </select>
          </div>
          <div v-if="sprite.layout === 'grid'" class="field inline"><label>列数</label><input type="number" v-model.number="sprite.columns" :min="1" /></div>
          <div class="field inline"><label>间距</label><input type="number" v-model.number="sprite.padding" :min="0" /></div>
          <div class="field inline"><label>帧宽</label><input type="number" v-model.number="sprite.frame_width" :min="1" placeholder="原始" /></div>
          <div class="field inline"><label>帧高</label><input type="number" v-model.number="sprite.frame_height" :min="1" placeholder="原始" /></div>
          <div class="field inline"><label>背景</label><input type="color" v-model="sprite.bg_color" /></div>
          <div class="field inline"><label>缩放算法</label>
            <select v-model="sprite.resample_filter">
              <option v-for="a in store.capabilities?.scale_algorithms || []" :key="a" :value="a">{{ a }}</option>
            </select>
          </div>
          <div class="field inline" v-if="format === 'sprite_sheet'"><label>生成JSON</label><input type="checkbox" v-model="sprite.generate_json" /></div>
        </div>

        <!-- GIF 配置 -->
        <div v-if="format === 'gif'" class="row" style="border-top:1px solid var(--border); padding-top:10px">
          <div class="field inline"><label>fps</label><input type="number" v-model.number="gif.fps" :min="1" :max="60" /></div>
          <div class="field inline"><label>循环</label><input type="number" v-model.number="gif.loop" :min="0" title="0=无限" /></div>
          <div class="field inline"><label>帧宽</label><input type="number" v-model.number="gif.frame_width" :min="1" /></div>
          <div class="field inline"><label>帧高</label><input type="number" v-model.number="gif.frame_height" :min="1" /></div>
          <div class="field inline"><label>优化</label><input type="checkbox" v-model="gif.optimize" /></div>
          <div class="field inline"><label>缩放算法</label>
            <select v-model="gif.resample_filter">
              <option v-for="a in store.capabilities?.scale_algorithms || []" :key="a" :value="a">{{ a }}</option>
            </select>
          </div>
        </div>

        <!-- WebP 配置 -->
        <div v-if="format === 'webp'" class="row" style="border-top:1px solid var(--border); padding-top:10px">
          <div class="field inline"><label>导出方式</label>
            <select v-model="webpIsSheet">
              <option :value="true">精灵图 WebP</option>
              <option :value="false">单独 WebP 帧</option>
            </select>
          </div>
          <div class="field inline"><label>质量</label><input type="number" v-model.number="webp.quality" :min="1" :max="100" /></div>
          <div class="field inline"><label>帧宽</label><input type="number" v-model.number="webp.frame_width" :min="1" placeholder="原始" /></div>
          <div class="field inline"><label>帧高</label><input type="number" v-model.number="webp.frame_height" :min="1" placeholder="原始" /></div>
        </div>

        <!-- Godot 配置 -->
        <div v-if="format === 'godot'" class="row" style="border-top:1px solid var(--border); padding-top:10px">
          <div class="field inline"><label>动画名</label><input v-model="godot.animation_name" /></div>
          <div class="field inline"><label>fps</label><input type="number" v-model.number="godot.fps" :min="1" :max="60" /></div>
          <div class="field inline"><label>循环</label><input type="checkbox" v-model="godot.loop" /></div>
          <div class="field inline"><label>导出单帧</label><input type="checkbox" v-model="godot.export_individual_frames" /></div>
          <div class="field inline"><label>帧宽</label><input type="number" v-model.number="godot.frame_width" :min="1" placeholder="原始" /></div>
          <div class="field inline"><label>帧高</label><input type="number" v-model.number="godot.frame_height" :min="1" placeholder="原始" /></div>
        </div>

        <!-- 循环过渡（与右侧预览面板共享设置） -->
        <div class="row" style="border-top:1px solid var(--border); padding-top:10px">
          <div class="field inline"><label>循环过渡</label>
            <input type="checkbox" :checked="store.loopTransition.enabled" @change="e => store.loopTransition.enabled = e.target.checked" />
          </div>
          <div v-if="store.loopTransition.enabled" class="field inline"><label>帧数</label>
            <input type="number" v-model.number="store.loopTransition.count" :min="1" :max="30" />
          </div>
          <div v-if="store.loopTransition.enabled" class="field inline"><label>模式</label>
            <select v-model="store.loopTransition.mode">
              <option value="blend">像素混合</option>
              <option value="align">轮廓对齐</option>
            </select>
          </div>
          <span class="hint">使导出的动画首尾无缝衔接</span>
        </div>

        <!-- PNG 压缩 -->
        <div class="row" style="border-top:1px solid var(--border); padding-top:10px">
          <div class="field inline"><label>PNG压缩</label><input type="checkbox" v-model="pngquant.enabled" /></div>
          <div v-if="pngquant.enabled">
            <div class="field inline"><label>质量范围</label>
              <input type="number" v-model.number="pngquant.quality_min" :min="0" :max="100" /> - <input type="number" v-model.number="pngquant.quality_max" :min="0" :max="100" />
            </div>
          </div>
        </div>

        <div class="row">
          <button class="primary" @click="doExport">开始导出</button>
        </div>
      </div>
    </div>

    <div>
      <div class="panel">
        <h3>导出记录</h3>
        <div v-for="ex in exports" :key="ex.name" class="job-item" style="margin-bottom:6px">
          <div class="row2">
            <span>{{ ex.name }}</span>
            <span>{{ fmtSize(ex.total_size) }}</span>
          </div>
          <div class="row" style="margin-top:4px">
            <span class="hint">{{ ex.files.map(f => f.name).join('、') }}</span>
            <button class="small" @click="downloadExport(ex)">下载</button>
          </div>
        </div>
        <p v-if="!exports.length" class="hint">暂无导出记录</p>
      </div>
    </div>
  </div>
</template>
