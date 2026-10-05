<template>
  <section class="page" data-module="insurance_claim">
    <header class="page-head">
      <div>
        <h2>保险理赔</h2>
        <p class="page-desc">按出险报案时间建档，记录受损设备、估损金额与保单免赔额；赔付金额依定损口径从严判定，结案后锁死。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记出险报案</button>
        <button class="btn" type="button" @click="exportRows">导出理赔台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="filter-bar create-bar" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="createForm[field.key]" :type="field.type" :placeholder="field.label" />
      </label>
      <button class="btn primary" type="submit">提交报案</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>案件编号 / 受损设备</span>
        <input v-model="filters.keyword" placeholder="按案件编号或受损设备检索" />
      </label>
      <label class="filter-item">
        <span>案件状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(column, cellValue(row, column)) }}</td>
          <td class="row-actions">
            <button v-if="row.status === '已报案'" class="link" type="button" @click="openAssess(row)">提交定损</button>
            <button v-if="row.status === '待赔付'" class="link" type="button" @click="runAction('结案', row)">结案</button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无理赔案件，可先登记出险报案</td>
        </tr>
      </tbody>
    </table>

    <div v-if="assessTarget" class="modal-mask" @click.self="assessTarget = null">
      <div class="modal-card">
        <h3>提交定损 · {{ assessTarget['案件编号'] }}</h3>
        <p class="page-desc">同一张定损单重复提交只认第一次；赔付金额按免赔额与赔付上限从严判定。</p>
        <label class="filter-item">
          <span>定损单号</span>
          <input v-model="assessForm['定损单号']" placeholder="如 DS-2026-0004" />
        </label>
        <label class="filter-item">
          <span>定损金额（元）</span>
          <input v-model="assessForm['定损金额']" type="number" min="0" step="0.01" placeholder="定损口径金额" />
        </label>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="submitAssess">确认提交</button>
          <button class="btn ghost" type="button" @click="assessTarget = null">取消</button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <h3>案件详情 · {{ detail['案件编号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ formatCell(field, cellValue(detail, field)) }}</dd>
          </template>
        </dl>
        <p class="page-desc">赔付结论与案件列表同源：赔付金额 {{ formatCell('赔付金额', detail['赔付金额']) }}（{{ detail['判定依据'] ?? '未判定' }}）。</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条理赔案件</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/insurance_claim'
const columns = ['案件编号', '报案时间', '出险时间', '受损设备', '估损金额', '定损金额', '赔付金额', '判定依据', '收款状态', '案件状态']
const statuses = ['已报案', '待赔付', '已结案']
const detailFields = ['案件编号', '出险时间', '报案时间', '受损设备', '估损金额', '保单号', '免赔额', '赔付上限', '定损单号', '定损金额', '定损时间', '赔付金额', '判定依据', '收款状态', '结案时间', '案件状态']
const createFields = [
  { key: '出险时间', label: '出险时间', type: 'date' },
  { key: '报案时间', label: '报案时间', type: 'date' },
  { key: '受损设备', label: '受损设备', type: 'text' },
  { key: '估损金额', label: '估损金额（元）', type: 'number' },
  { key: '保单号', label: '保单号', type: 'text' },
  { key: '免赔额', label: '免赔额（元）', type: 'number' },
  { key: '赔付上限', label: '赔付上限（元）', type: 'number' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const stats = ref([
  { label: '在办案件', value: 0 },
  { label: '待收款金额（元）', value: '0.00' },
  { label: '累计赔付（元）', value: '0.00' },
])
const showCreate = ref(false)
const createForm = reactive<Record<string, string>>({})
const assessTarget = ref<Row | null>(null)
const assessForm = reactive<Record<string, string>>({ 定损单号: '', 定损金额: '' })
const detail = ref<Row | null>(null)

const amountColumns = new Set(['估损金额', '定损金额', '赔付金额', '免赔额', '赔付上限'])

function cellValue(row: Row, column: string): string | number | null | undefined {
  // 工作流状态存在 status 键里，中文列名做一次映射，保证列表与详情口径一致
  if (column === '案件状态') return row.status
  return row[column]
}

function formatCell(column: string, value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (amountColumns.has(column)) {
    const num = Number(value)
    return Number.isFinite(num) ? num.toFixed(2) : String(value)
  }
  return String(value)
}

function toNumber(value: string | number | null | undefined): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : 0
}

function refreshStats() {
  const pending = rows.value.filter((row) => row.status !== '已结案').length
  const receivable = rows.value
    .filter((row) => row['收款状态'] === '待收款')
    .reduce((sum, row) => sum + toNumber(row['赔付金额']), 0)
  const paid = rows.value.reduce((sum, row) => sum + toNumber(row['赔付金额']), 0)
  stats.value = [
    { label: '在办案件', value: pending },
    { label: '待收款金额（元）', value: receivable.toFixed(2) },
    { label: '累计赔付（元）', value: paid.toFixed(2) },
  ]
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function readResult(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(payload?.detail ?? fallback)
  }
  if (payload && payload.ok === false) {
    throw new Error(payload.message ?? fallback)
  }
  return payload
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await readResult(response, '出险报案登记失败')
    noticeMessage.value = payload?.message ?? '出险报案已登记'
    showCreate.value = false
    Object.keys(createForm).forEach((key) => delete createForm[key])
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出险报案登记失败'
  }
}

function openAssess(row: Row) {
  assessForm['定损单号'] = ''
  assessForm['定损金额'] = ''
  assessTarget.value = row
}

async function submitAssess() {
  if (!assessTarget.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${assessTarget.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '提交定损', ...assessForm } }),
    })
    const payload = await readResult(response, '定损提交失败')
    noticeMessage.value = payload?.message ?? '定损已提交'
    assessTarget.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '定损提交失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await readResult(response, '保险理赔动作未生效，请稍后重试')
    noticeMessage.value = payload?.message ?? '操作已完成'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保险理赔操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    detail.value = await fetchJson<Row>(`${ENDPOINT}/${row.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '案件详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('理赔案件列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    refreshStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理赔案件列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.create-bar {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
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
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  width: 420px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal-card h3 {
  margin: 0;
  font-size: 15px;
}
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
.notice-text {
  color: #067647;
}
select {
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
</style>
