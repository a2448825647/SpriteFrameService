// 后台任务跟踪：提交 + 轮询进度 + 结果
import { reactive } from 'vue'
import api from './api'
import { toast } from './stores'

const jobs = reactive({ items: [] })   // 最近的 job，含轮询句柄

let pollTimers = {}

export function useJobs() {
  return jobs
}

export async function startJob(startFn, { onDone, title } = {}) {
  let jobId
  try {
    const res = await startFn()
    jobId = res.job_id
  } catch (e) {
    toast(`任务启动失败: ${e.message}`)
    throw e
  }

  const item = reactive({
    id: jobId,
    title: title || '任务',
    status: 'queued',
    progress: 0,
    message: '',
    result: null,
    error: null,
  })
  jobs.items.unshift(item)
  if (jobs.items.length > 30) jobs.items.pop()

  const tick = async () => {
    try {
      const j = await api.job(jobId)
      item.status = j.status
      item.progress = j.progress
      item.message = j.message
      item.result = j.result
      item.error = j.error
      if (j.status === 'done') {
        stopPoll(jobId)
        toast(`${item.title} 完成`)
        if (onDone) onDone(j.result)
      } else if (j.status === 'error') {
        stopPoll(jobId)
        toast(`${item.title} 失败: ${(j.error || '').split('\n')[0]}`)
      } else if (j.status === 'cancelled') {
        stopPoll(jobId)
      } else {
        pollTimers[jobId] = setTimeout(tick, 400)
      }
    } catch (e) {
      // 网络瞬断时继续轮询
      pollTimers[jobId] = setTimeout(tick, 1500)
    }
  }
  pollTimers[jobId] = setTimeout(tick, 200)

  return item
}

export async function cancelJob(jobId) {
  try {
    await api.cancelJob(jobId)
  } catch { /* ignore */ }
}

function stopPoll(jobId) {
  if (pollTimers[jobId]) {
    clearTimeout(pollTimers[jobId])
    delete pollTimers[jobId]
  }
}
