<template>
  <section class="page" data-module="claim_receivable">
    <header class="page-head">
      <div>
        <h2>待收款台账</h2>
        <p class="page-desc">赔付结论自动落入财务待收款台账，登记收款后理赔案件的收款状态随之更新。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出待收款台账</button>
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
        <span>台账编号 / 案件编号</span>
        <input v-model="filters.keyword" placeholder="按台账编号或案件编号检索" />
      </label>
      <label class="filter-item">
        <span>收款状态</span>
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
          <td v-for="column in columns" :key="column">{{ formatCell(column, row[column]) }}</td>
          <td class="row-actions">
            <button v-if="row['收款状态'] === '待收款'" class="link" type="button" @click="runAction('登记收款', row)">登记收款</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无待收款记录，赔付结论生成后自动入账</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条待收款记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/claim_receivable'
const columns = ['台账编号', '案件编号', '赔付金额', '收款状态', '登记时间', '收款时间']
const statuses = ['待收款', '已收款']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const stats = ref([
  { label: '待收款笔数', value: 0 },
  { label: '待收款金额（元）', value: '0.00' },
  { label: '已收款金额（元）', value: '0.00' },
])

function formatCell(column: string, value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (column === '赔付金额') {
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
  const pendingRows = rows.value.filter((row) => row['收款状态'] === '待收款')
  const received = rows.value
    .filter((row) => row['收款状态'] === '已收款')
    .reduce((sum, row) => sum + toNumber(row['赔付金额']), 0)
  stats.value = [
    { label: '待收款笔数', value: pendingRows.length },
    { label: '待收款金额（元）', value: pendingRows.reduce((sum, row) => sum + toNumber(row['赔付金额']), 0).toFixed(2) },
    { label: '已收款金额（元）', value: received.toFixed(2) },
  ]
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(payload?.detail ?? '待收款台账动作未生效，请稍后重试')
    }
    if (payload && payload.ok === false) {
      throw new Error(payload.message ?? '待收款台账动作未生效，请稍后重试')
    }
    noticeMessage.value = payload?.message ?? '操作已完成'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待收款台账操作失败'
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
      throw new Error('待收款台账读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    refreshStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待收款台账读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.notice-text {
  color: #067647;
}
select {
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
</style>
