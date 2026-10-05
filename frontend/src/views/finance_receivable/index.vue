<template>
  <section class="page" data-module="finance_receivable">
    <header class="page-head">
      <div>
        <h2>财务待收款台账</h2>
        <p class="page-desc">理赔案件结案后自动落账；确认到账后同步更新案件收款状态，赔付金额以结案锁定值为准。</p>
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
        <span>收款状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option value="待收款">待收款</option>
          <option value="已收款">已收款</option>
          <option value="零赔付结案">零赔付结案</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="status = ''; void reload()">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>财务动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-if="row.收款状态 === '待收款'"
              class="link"
              type="button"
              @click="confirmReceived(row)"
            >
              确认到账
            </button>
            <span v-else>—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无待收款记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条待收款记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { postJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type ActionResponse = { ok: boolean; message: string; entry: Row }

const ENDPOINT = '/api/finance_receivables'
const columns = ['待收款编号', '案件编号', '款项来源', '应收金额', '币种', '收款状态', '预计到账日', '到账时间', '建档时间']
const rows = ref<Row[]>([])
const total = ref(0)
const status = ref('')
const errorMessage = ref('')
const stats = ref([
  { label: '待收款笔数', value: 0 },
  { label: '待收金额', value: '0.00 元' },
  { label: '已收款笔数', value: 0 },
  { label: '已收金额', value: '0.00 元' },
  { label: '零赔付结案', value: 0 },
])

async function confirmReceived(row: Row) {
  errorMessage.value = ''
  try {
    await postJson<ActionResponse>(`${ENDPOINT}/${row.id}/confirm-received`, {})
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认到账失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (status.value) query.set('status', status.value)
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok || !statsResponse.ok) throw new Error('待收款台账读取失败')
    const payload = await listResponse.json()
    const statPayload = await statsResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = statPayload.items ?? stats.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待收款台账读取失败'
  }
}

onMounted(reload)
</script>
