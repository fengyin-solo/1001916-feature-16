<template>
  <section class="page" data-module="maintjob">
    <header class="page-head">
      <div>
        <h2>检修任务管理</h2>
        <p class="page-desc">作业班组可一次勾选多条检修单，填写检修类型与计划工时后整批派发；某条不满足条件只拦该条，其余照常派发。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检修任务单</button>
        <button class="btn" type="button" @click="exportRows">导出检修任务清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
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

    <!-- 批量操作条：勾选后整批派发或拉回待派发 -->
    <div class="batch-bar">
      <div class="batch-field">
        <span>已勾选 <strong>{{ selectedIds.size }}</strong> 条</span>
      </div>
      <label class="batch-field">
        <span>作业班组</span>
        <select v-model="batchTeam" :disabled="!selectedIds.size">
          <option value="">请选择作业班组</option>
          <option v-for="team in teams" :key="team.作业班组" :value="team.作业班组">
            {{ team.作业班组 }}（剩余 {{ formatHours(team.剩余工时) }}/{{ team.工时上限 }} 工时）
          </option>
        </select>
      </label>
      <button class="btn primary" type="button" :disabled="!selectedIds.size || batchBusy" @click="submitBatch('派发任务')">
        整批派发
      </button>
      <button class="btn" type="button" :disabled="!selectedIds.size || batchBusy" @click="submitBatch('拉回待派发')">
        批量拉回待派发
      </button>
      <button class="btn ghost" type="button" :disabled="!selectedIds.size" @click="clearSelection">清空勾选</button>
      <span v-if="batchError" class="error-text">{{ batchError }}</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allVisibleSelected"
              :indeterminate.prop="someVisibleSelected && !allVisibleSelected"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>批量派发填写</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-selected': selectedIds.has(Number(row.id)) }">
          <td class="check-col">
            <input type="checkbox" :checked="selectedIds.has(Number(row.id))" @change="toggleRow(Number(row.id))" />
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">{{ row['任务编号'] ?? '—' }}</button>
          </td>
          <td>{{ row['关联机组'] || '—' }}</td>
          <td>{{ row['检修类型'] || '—' }}</td>
          <td>{{ row['计划开始日'] || '—' }}</td>
          <td>{{ formatHours(row['计划工时']) }}</td>
          <td>{{ row['作业班组'] || '—' }}</td>
          <td>{{ row['负责人'] || '—' }}</td>
          <td>
            <span :class="['status-tag', statusClass(row)]">{{ row.status ?? '—' }}</span>
          </td>
          <td class="batch-edit">
            <template v-if="row.status === '待派发'">
              <input v-model="drafts[Number(row.id)].检修类型" placeholder="检修类型" aria-label="检修类型" />
              <input v-model="drafts[Number(row.id)].计划工时" placeholder="计划工时" aria-label="计划工时" />
            </template>
            <span v-else class="muted-text">派发时无需填写</span>
          </td>
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
          <td :colspan="columns.length + 3" class="empty-state">暂无检修任务数据，可先登记检修任务单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修任务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 整批提交后的逐条派发结果 -->
    <div v-if="batchResult" class="result-panel">
      <header class="result-head">
        <strong>{{ batchResult.message }}</strong>
        <button class="link" type="button" @click="batchResult = null">关闭结果</button>
      </header>
      <ul class="result-list">
        <li v-for="item in batchResult.results" :key="item.id" :class="item.ok ? 'result-ok' : 'result-fail'">
          <span class="result-mark">{{ item.ok ? '✓' : '✗' }}</span>
          <span class="result-code">{{ item['任务编号'] ?? `#${item.id}` }}</span>
          <span>{{ item.message }}</span>
        </li>
      </ul>
    </div>

    <!-- 检修单详情：与列表共用同一份后端口径 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <header class="modal-head">
          <strong>检修任务单详情 · {{ detail['任务编号'] }}</strong>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd v-if="column === '作业班组'">{{ detail[column] || '—' }}</dd>
            <dd v-else-if="column === '计划工时'">{{ formatHours(detail[column]) }}</dd>
            <dd v-else>{{ detail[column] || '—' }}</dd>
          </template>
        </dl>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Team = { 作业班组: string; 工时上限: number; 已排工时: number; 剩余工时: number }
type BatchItemResult = {
  id: number
  任务编号: string | null
  ok: boolean
  message: string
  entry: Row | null
}
type BatchResponse = {
  ok: boolean
  message: string
  action: string
  success_count: number
  failed_count: number
  results: BatchItemResult[]
}

const ENDPOINT = '/api/maintjob'
const columns = ['任务编号', '关联机组', '检修类型', '计划开始日', '计划工时', '作业班组', '负责人', '任务状态']
const statuses = ['待派发', '已派发', '检修中', '已完成']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const teams = ref<Team[]>([])
const selectedIds = reactive(new Set<number>())
const drafts = reactive<Record<number, { 检修类型: string; 计划工时: string }>>({})
const batchTeam = ref('')
const batchBusy = ref(false)
const batchError = ref('')
const batchResult = ref<BatchResponse | null>(null)
const detail = ref<Row | null>(null)

const stats = computed(() => {
  const pending = rows.value.filter((row) => row.status === '待派发').length
  const doing = rows.value.filter((row) => row.status === '检修中').length
  const done = rows.value.filter((row) => row.status === '已完成').length
  return [
    { label: '待派发任务', value: pending },
    { label: '检修中任务', value: doing },
    { label: '已完成任务', value: done },
  ]
})

const visibleIds = computed(() => rows.value.map((row) => Number(row.id)))
const allVisibleSelected = computed(
  () => visibleIds.value.length > 0 && visibleIds.value.every((id) => selectedIds.has(id)),
)
const someVisibleSelected = computed(() => visibleIds.value.some((id) => selectedIds.has(id)))

function formatHours(value: Row[string] | undefined): string {
  if (value === null || value === undefined || String(value).trim() === '') return '—'
  const num = Number(value)
  return Number.isFinite(num) ? String(num) : String(value)
}

function statusClass(row: Row): string {
  return {
    待派发: 'status-pending',
    已派发: 'status-dispatched',
    检修中: 'status-doing',
    已完成: 'status-done',
  }[String(row.status ?? '')] ?? ''
}

function availableActions(row: Row): string[] {
  switch (row.status) {
    case '待派发':
      return ['派发任务']
    case '已派发':
      return ['开始检修']
    case '检修中':
      return ['确认完成']
    default:
      return []
  }
}

function ensureDraft(id: number): { 检修类型: string; 计划工时: string } {
  if (!drafts[id]) {
    drafts[id] = { 检修类型: '', 计划工时: '' }
  }
  return drafts[id]
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检修任务单登记入口尚未接入审批流'
}

function toggleRow(id: number) {
  if (selectedIds.has(id)) {
    selectedIds.delete(id)
  } else {
    selectedIds.add(id)
    const row = rows.value.find((item) => Number(item.id) === id)
    if (row) {
      const draft = ensureDraft(id)
      if (!draft.检修类型) draft.检修类型 = String(row['检修类型'] ?? '')
      if (!draft.计划工时) draft.计划工时 = formatHours(row['计划工时']) === '—' ? '' : String(row['计划工时'])
    }
  }
}

function toggleAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  visibleIds.value.forEach((id) => {
    if (checked) {
      selectedIds.add(id)
      const row = rows.value.find((item) => Number(item.id) === id)
      if (row) {
        const draft = ensureDraft(id)
        if (!draft.检修类型) draft.检修类型 = String(row['检修类型'] ?? '')
        if (!draft.计划工时) draft.计划工时 = formatHours(row['计划工时']) === '—' ? '' : String(row['计划工时'])
      }
    } else {
      selectedIds.delete(id)
    }
  })
}

function clearSelection() {
  selectedIds.clear()
}

async function loadTeams() {
  try {
    const response = await request(`${ENDPOINT}/teams`)
    if (response.ok) {
      const payload = (await response.json()) as { items: Team[] }
      teams.value = payload.items ?? []
    }
  } catch {
    teams.value = []
  }
}

async function submitBatch(action: '派发任务' | '拉回待派发') {
  batchError.value = ''
  batchResult.value = null
  if (!selectedIds.size) {
    batchError.value = '请先勾选需要处理的检修任务单'
    return
  }
  if (action === '派发任务' && !batchTeam.value) {
    batchError.value = '整批派发前请选择作业班组'
    return
  }

  // 同一张检修单在页面上只可能勾选一次；提交顺序按列表顺序，便于结果核对
  const items = rows.value
    .filter((row) => selectedIds.has(Number(row.id)))
    .map((row) => {
      const id = Number(row.id)
      const draft = ensureDraft(id)
      return {
        id,
        检修类型: draft.检修类型,
        计划工时: draft.计划工时 === '' ? null : Number(draft.计划工时),
      }
    })

  batchBusy.value = true
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ action, 作业班组: batchTeam.value, items }),
    })
    const payload = (await response.json().catch(() => null)) as BatchResponse | { detail?: string } | null
    if (!response.ok) {
      throw new Error((payload && 'detail' in payload && payload.detail) || '批量提交未生效，请稍后重试')
    }
    batchResult.value = payload as BatchResponse
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量提交失败'
  } finally {
    batchBusy.value = false
    clearSelection()
    await Promise.all([reload(), loadTeams()])
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '检修任务动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadTeams()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('检修任务单详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('检修任务单列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    rows.value.forEach((row) => {
      const id = Number(row.id)
      if (!drafts[id]) {
        drafts[id] = {
          检修类型: String(row['检修类型'] ?? ''),
          计划工时: formatHours(row['计划工时']) === '—' ? '' : String(row['计划工时']),
        }
      }
    })
    // 清理已不在当前列表中的勾选，避免翻页/筛选后带着不可见的单子提交
    const validIds = new Set(rows.value.map((row) => Number(row.id)))
    ;[...selectedIds].forEach((id) => {
      if (!validIds.has(id)) selectedIds.delete(id)
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修任务列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadTeams()
})
</script>

<style scoped>
.batch-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.batch-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.batch-field select {
  min-width: 240px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.check-col {
  width: 36px;
  text-align: center;
}
.row-selected {
  background: #eef5ff;
}
.batch-edit {
  display: flex;
  gap: 6px;
}
.batch-edit input {
  width: 96px;
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 12px;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.status-pending {
  background: #fef3c7;
  color: #92400e;
}
.status-dispatched {
  background: #dbeafe;
  color: #1e40af;
}
.status-doing {
  background: #e0e7ff;
  color: #3730a3;
}
.status-done {
  background: #dcfce7;
  color: #166534;
}
.result-panel {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.result-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.result-list li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 13px;
}
.result-code {
  min-width: 84px;
  font-weight: 600;
}
.result-mark {
  font-weight: 700;
}
.result-ok {
  color: #166534;
}
.result-fail {
  color: #b42318;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 560px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr 96px 1fr;
  gap: 8px 12px;
  margin: 0;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
</style>
