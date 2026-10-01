<template>
  <section class="page" data-module="maintjob">
    <header class="page-head">
      <div>
        <h2>检修任务管理</h2>
        <p class="page-desc">作业班组可一次勾选多条检修任务单，填写检修类型与计划工时后整批派发，逐条查看派发结果。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openBatch('派发任务')">
          批量派发
        </button>
        <button class="btn danger" type="button" :disabled="!selectedIds.length" @click="openBatch('批量拉回')">
          批量拉回
        </button>
        <button class="btn" type="button" @click="exportRows">导出检修任务清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="batch-bar">
      <label>
        <input type="checkbox" :checked="allVisibleSelected" :indeterminate.prop="someVisibleSelected" @change="toggleAll" />
        全选本页
      </label>
      <span>已勾选 <span class="selected-count">{{ selectedIds.length }}</span> 条检修任务单</span>
      <button class="link" type="button" :disabled="!selectedIds.length" @click="clearSelection">清空勾选</button>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>任务编号</span>
        <input v-model="keyword" placeholder="按任务编号检索" />
      </label>
      <label class="filter-item">
        <span>任务状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 36px"></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input type="checkbox" :checked="isSelected(Number(row.id))" @change="toggleOne(Number(row.id))" />
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(Number(row.id))">{{ row['任务编号'] }}</button>
          </td>
          <td>{{ row['关联机组'] || '—' }}</td>
          <td>{{ row['检修类型'] || '—' }}</td>
          <td>{{ row['计划开始日'] || '—' }}</td>
          <td>{{ row['计划工时'] ?? '—' }}</td>
          <td>{{ row['作业班组'] || '待派发' }}</td>
          <td>{{ row['负责人'] || '—' }}</td>
          <td>{{ row['任务状态'] }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的检修任务数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修任务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 批量派发 / 批量拉回 -->
    <div v-if="batch.open" class="modal-mask" @click.self="closeBatch">
      <div class="modal wide">
        <div class="modal-head">
          <h3>{{ batch.action }}（已勾选 {{ selectedRows.length }} 条）</h3>
          <button class="modal-close" type="button" @click="closeBatch">×</button>
        </div>

        <div class="form-grid">
          <label>
            <span>作业班组 *</span>
            <input v-model="batch.crew" list="crew-options" placeholder="如：运维一班" @input="loadCapacity" />
            <datalist id="crew-options">
              <option v-for="c in crewOptions" :key="c" :value="c"></option>
            </datalist>
          </label>
        </div>
        <p v-if="capacity && batch.action === '派发任务'" class="capacity-hint" :class="{ over: capacity.remaining_hours <= 0 }">
          班组「{{ capacity.crew }}」本周期工时 {{ capacity.used_hours }}/{{ capacity.total_hours }}，
          剩余可用 <strong>{{ capacity.remaining_hours }}</strong> 工时（提交时按顺序逐条扣减）
        </p>

        <table v-if="batch.action === '派发任务'" class="data-table">
          <thead>
            <tr>
              <th>任务编号</th>
              <th>当前状态</th>
              <th>关联机组</th>
              <th style="width: 170px">检修类型 *</th>
              <th style="width: 120px">计划工时 *</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in selectedRows" :key="String(row.id)">
              <td>{{ row['任务编号'] }}</td>
              <td>{{ row['任务状态'] }}</td>
              <td>{{ row['关联机组'] || '—' }}</td>
              <td class="cell-edit">
                <input v-model="edits[Number(row.id)].检修类型" placeholder="填写检修类型" />
              </td>
              <td class="cell-edit">
                <input v-model="edits[Number(row.id)].计划工时" class="invalid" :class="{ invalid: !hoursValid(row) }" placeholder="工时（小时）" />
              </td>
            </tr>
          </tbody>
        </table>
        <table v-else class="data-table">
          <thead>
            <tr><th>任务编号</th><th>当前状态</th><th>作业班组</th><th>计划工时</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in selectedRows" :key="String(row.id)">
              <td>{{ row['任务编号'] }}</td>
              <td>{{ row['任务状态'] }}</td>
              <td>{{ row['作业班组'] || '待派发' }}</td>
              <td>{{ row['计划工时'] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p class="capacity-hint">提示：仅「待派发」的任务单可派发；缺少关联机组或计划工时超出班组剩余工时时，该条会被单独拦截，其余照常处理。验收通过的任务单不允许拉回。</p>

        <div v-if="batch.error" class="error-text">{{ batch.error }}</div>

        <div v-if="batch.result" class="result-panel">
          <div class="result-head">
            派发结果：成功 {{ batch.result.success_count }} 条，拦截 {{ batch.result.failed_count }} 条
            <span v-if="batch.result.remaining_hours !== null">
              ｜班组剩余工时 {{ batch.result.remaining_hours }}
            </span>
          </div>
          <div v-for="r in batch.result.results" :key="r.id" class="result-row">
            <span class="tag" :class="r.ok ? 'ok' : 'fail'">{{ r.ok ? '成功' : '拦截' }}</span>
            <span>{{ r.task_no ?? `#${r.id}` }}</span>
            <span>{{ r.message }}</span>
          </div>
        </div>

        <div class="modal-foot">
          <button class="btn" type="button" @click="closeBatch">{{ batch.result ? '关闭' : '取消' }}</button>
          <button v-if="!batch.result" class="btn primary" type="button" :disabled="batch.submitting" @click="submitBatch">
            {{ batch.submitting ? '提交中…' : '提交' }}
          </button>
          <button v-else class="btn primary" type="button" @click="afterBatchDone">继续处理</button>
        </div>
      </div>
    </div>

    <!-- 任务单详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <div class="modal-head">
          <h3>检修任务单详情 · {{ detail['任务编号'] }}</h3>
          <button class="modal-close" type="button" @click="detail = null">×</button>
        </div>
        <div class="detail-grid">
          <template v-for="column in columns" :key="column">
            <div>
              <span class="k">{{ column }}</span>
              <span>{{ detailColumn(column) }}</span>
            </div>
          </template>
        </div>
        <div class="modal-foot">
          <button class="btn primary" type="button" @click="detail = null">知道了</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type BatchItemResult = {
  id: number
  task_no: string | null
  ok: boolean
  message: string
  entry: Row | null
}
type BatchResult = {
  ok: boolean
  message: string
  remaining_hours: number | null
  success_count: number
  failed_count: number
  results: BatchItemResult[]
}
type Capacity = { crew: string; total_hours: number; used_hours: number; remaining_hours: number }

const ENDPOINT = '/api/maintjob'
const columns = ["任务编号", "关联机组", "检修类型", "计划开始日", "计划工时", "作业班组", "负责人", "任务状态"]
const statuses = ["待派发", "已派发", "检修中", "已完成"]
const stats = ref([{ label: "待派发任务", value: 0 }, { label: "已派发/检修中", value: 0 }, { label: "已完成任务", value: 0 }])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const selectedIds = ref<number[]>([])
const crewOptions = ref<string[]>([])

const detail = ref<Row | null>(null)

const batch = reactive({
  open: false,
  action: '派发任务' as '派发任务' | '批量拉回',
  crew: '',
  submitting: false,
  error: '',
  result: null as BatchResult | null,
})
const edits = reactive<Record<number, { 检修类型: string; 计划工时: string }>>({})
const capacity = ref<Capacity | null>(null)

const selectedRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(Number(row.id))))
const allVisibleSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))))
const someVisibleSelected = computed(() => !allVisibleSelected.value && rows.value.some((row) => selectedIds.value.includes(Number(row.id))))

function availableActions(row: Row): string[] {
  switch (row['任务状态']) {
    case '待派发':
      return []
    case '已派发':
      return ['开始检修']
    case '检修中':
      return ['确认完成']
    default:
      return []
  }
}

function isSelected(id: number | string): boolean {
  return selectedIds.value.includes(Number(id))
}

function toggleOne(id: number | string) {
  const nid = Number(id)
  if (isSelected(nid)) {
    selectedIds.value = selectedIds.value.filter((x) => x !== nid)
  } else {
    selectedIds.value = [...selectedIds.value, nid]
  }
}

function toggleAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const visibleIds = rows.value.map((row) => Number(row.id))
  const kept = selectedIds.value.filter((id) => !visibleIds.includes(id))
  selectedIds.value = checked ? [...kept, ...visibleIds] : kept
}

function clearSelection() {
  selectedIds.value = []
}

function hoursValid(row: Row): boolean {
  const raw = (edits[Number(row.id)]?.计划工时 ?? '').trim()
  if (!raw) return false
  const hours = Number(raw)
  return Number.isFinite(hours) && hours > 0
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('检修任务动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message ?? '操作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务操作失败'
  }
}

async function openDetail(id: number) {
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (!response.ok) throw new Error('任务单详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '任务单详情读取失败'
  }
}

function detailColumn(column: string): string {
  if (!detail.value) return '—'
  const value = detail.value[column]
  if (column === '作业班组') return String(value || '待派发')
  return String(value ?? '—')
}

function openBatch(action: '派发任务' | '批量拉回') {
  if (!selectedIds.value.length) return
  batch.open = true
  batch.action = action
  batch.crew = ''
  batch.error = ''
  batch.result = null
  batch.submitting = false
  capacity.value = null
  // 用行内现有值预填，作业班组可逐条调整检修类型与计划工时。
  for (const row of selectedRows.value) {
    edits[Number(row.id)] = {
      检修类型: String(row['检修类型'] ?? ''),
      计划工时: row['计划工时'] == null ? '' : String(row['计划工时']),
    }
  }
  const firstCrew = selectedRows.value.map((row) => String(row['作业班组'] || '')).find(Boolean)
  if (firstCrew) {
    batch.crew = firstCrew
    void loadCapacity()
  }
}

function closeBatch() {
  batch.open = false
  batch.result = null
}

let capacitySeq = 0
async function loadCapacity() {
  const crew = batch.crew.trim()
  const seq = ++capacitySeq
  if (!crew) {
    capacity.value = null
    return
  }
  try {
    const response = await request(`${ENDPOINT}/crew-capacity?crew=${encodeURIComponent(crew)}`)
    if (!response.ok) return
    const data: Capacity = await response.json()
    if (seq === capacitySeq) capacity.value = data
  } catch {
    // 容量查询失败不阻断填表，提交时仍以服务端口径为准。
  }
}

async function submitBatch() {
  batch.error = ''
  const crew = batch.crew.trim()
  if (!crew) {
    batch.error = '请先填写作业班组'
    return
  }
  if (batch.action === '派发任务') {
    const badType = selectedRows.value.some((row) => !edits[Number(row.id)]?.检修类型?.trim())
    const badHours = selectedRows.value.some((row) => !hoursValid(row))
    if (badType || badHours) {
      batch.error = `存在未填检修类型${badHours ? '或计划工时无效（需为正数）' : ''}的任务单，请修正；缺少关联机组等问题将在提交后逐条反馈。`
      return
    }
  }

  const items = selectedRows.value.map((row) => {
    const id = Number(row.id)
    if (batch.action === '派发任务') {
      return {
        id,
        values: {
          检修类型: edits[id].检修类型.trim(),
          计划工时: edits[id].计划工时.trim(),
        },
      }
    }
    return { id, values: {} }
  })

  batch.submitting = true
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action: batch.action, crew, items }),
    })
    const data: BatchResult = await response.json()
    if (!response.ok) {
      throw new Error((data as unknown as { detail?: string }).detail ?? '批量操作未生效，请稍后重试')
    }
    batch.result = data
    refreshCrewOptions(crew)
    await reload()
  } catch (error) {
    batch.error = error instanceof Error ? error.message : '批量操作失败'
  } finally {
    batch.submitting = false
  }
}

async function afterBatchDone() {
  // 被拦截的条目保留勾选，便于补录后重新提交；成功的条目从勾选里去掉。
  if (batch.result) {
    const doneIds = batch.result.results.filter((r) => r.ok).map((r) => r.id)
    selectedIds.value = selectedIds.value.filter((id) => !doneIds.includes(id))
  }
  closeBatch()
}

function refreshCrewOptions(crew: string) {
  if (crew && !crewOptions.value.includes(crew)) {
    crewOptions.value = [...crewOptions.value, crew].sort()
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('检修任务单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await reloadStats()
    const crews = [...new Set(rows.value.map((r) => String(r['作业班组'] || '')).filter(Boolean))]
    for (const c of crews) refreshCrewOptions(c)
    // 丢弃已不在列表中的勾选项（如被筛选掉），避免提交到看不见的单据。
    const ids = new Set(rows.value.map((r) => Number(r.id)))
    selectedIds.value = selectedIds.value.filter((id) => ids.has(id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务列表读取失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}?size=200`)
    if (!response.ok) return
    const payload = await response.json()
    const all: Row[] = payload.items ?? []
    stats.value = [
      { label: '待派发任务', value: all.filter((r) => r['任务状态'] === '待派发').length },
      { label: '已派发/检修中', value: all.filter((r) => ['已派发', '检修中'].includes(String(r['任务状态']))).length },
      { label: '已完成任务', value: all.filter((r) => r['任务状态'] === '已完成').length },
    ]
  } catch {
    // 统计卡片失败不影响主列表。
  }
}

onMounted(reload)
</script>
