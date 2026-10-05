<template>
  <section class="page" data-module="insurance_claim">
    <header class="page-head">
      <div>
        <h2>保险理赔案件台账</h2>
        <p class="page-desc">按报案时间建档，记录受损设备、估损金额与保单条款；定损后只按更严规则保留一个赔付结论。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">出险报案建档</button>
        <button class="btn" type="button" @click="openBackfill">回填存量案件</button>
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
        <span>案件编号/受损设备</span>
        <input v-model="keyword" placeholder="输入关键字检索" />
      </label>
      <label class="filter-item">
        <span>案件状态</span>
        <select v-model="status">
          <option value="">全部</option>
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
          <td v-for="column in columns" :key="column">
            <button v-if="column === '案件编号'" class="link" type="button" @click="viewDetail(row)">{{ row[column] }}</button>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="viewDetail(row)">详情</button>
            <button v-if="row.案件状态 === '已报案'" class="link" type="button" @click="openAssessment(row)">提交定损</button>
            <button v-if="row.案件状态 === '已定损'" class="link" type="button" @click="closeClaim(row)">结案锁定</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保险理赔案件</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条理赔案件</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="formMode" class="modal-mask" @click.self="closeForm">
      <form class="modal-panel" @submit.prevent="submitForm">
        <h3>{{ formTitle }}</h3>
        <p v-if="formMode === 'assessment'" class="page-desc">
          当前案件：{{ activeRow?.['案件编号'] }}。同一定损单重复提交只认第一次。
        </p>
        <div v-for="field in visibleFields" :key="field.key" class="form-line">
          <label>
            <span>{{ field.label }}</span>
            <input
              v-model="form[field.key]"
              :type="field.type"
              :step="field.type === 'number' ? '0.01' : undefined"
              :required="field.required"
            />
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="submit">提交</button>
        </div>
      </form>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <article class="modal-panel detail-panel">
        <h3>案件详情 · {{ detail['案件编号'] }}</h3>
        <div class="detail-grid">
          <div v-for="field in detailFields" :key="field">
            <span>{{ field }}</span>
            <strong>{{ detail[field] ?? '—' }}</strong>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
          <button v-if="detail.案件状态 === '已报案'" class="btn primary" type="button" @click="openAssessment(detail)">提交定损</button>
          <button v-if="detail.案件状态 === '已定损'" class="btn primary" type="button" @click="closeClaim(detail)">结案锁定</button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { postJson, request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type ActionResponse = { ok: boolean; message: string; entry: Row }

type FormField = {
  key: string
  label: string
  type?: string
  required?: boolean
}

const ENDPOINT = '/api/insurance_claims'
const columns = ['案件编号', '出险时间', '报案时间', '受损设备', '估损金额', '保单免赔额', '保单赔付上限', '案件状态', '定损口径', '赔付金额', '从严规则', '赔付结论', '收款状态']
const detailFields = [...columns, '保单号', '保单条款', '定损单号', '定损金额', '结案时间', '到账时间', '备注']
const statuses = ['已报案', '已定损', '已结案']
const stats = ref([
  { label: '待定损案件', value: 0 },
  { label: '已定款待结案', value: 0 },
  { label: '已结案件', value: 0 },
  { label: '财务待收赔款', value: '0.00 元' },
])

const rows = ref<Row[]>([])
const total = ref(0)
const keyword = ref('')
const status = ref('')
const errorMessage = ref('')
const formMode = ref<'create' | 'backfill' | 'assessment' | ''>('')
const activeRow = ref<Row | null>(null)
const detail = ref<Row | null>(null)
const form = reactive<Record<string, string>>({})

const createFields: FormField[] = [
  { key: 'case_no', label: '案件编号', required: true },
  { key: 'occurred_at', label: '出险时间', type: 'datetime-local', required: true },
  { key: 'reported_at', label: '报案时间', type: 'datetime-local', required: true },
  { key: 'damaged_equipment', label: '受损设备', required: true },
  { key: 'estimated_loss', label: '估损金额', type: 'number', required: true },
  { key: 'deductible', label: '保单免赔额', type: 'number', required: true },
  { key: 'payout_cap', label: '赔付上限', type: 'number', required: true },
  { key: 'policy_no', label: '保单号' },
  { key: 'policy_version', label: '保单条款版本', required: true },
]
const backfillFields: FormField[] = [
  { key: 'case_no', label: '案件编号', required: true },
  { key: 'occurred_at', label: '出险时间（按此回填）', type: 'datetime-local', required: true },
  { key: 'reported_at', label: '报案时间（可空）' },
  { key: 'damaged_equipment', label: '受损设备', required: true },
  { key: 'estimated_loss', label: '估损金额', type: 'number', required: true },
  { key: 'deductible', label: '原保单免赔额', type: 'number', required: true },
  { key: 'payout_cap', label: '原赔付上限', type: 'number', required: true },
  { key: 'policy_version', label: '原保单条款', required: true },
  { key: 'assessment_no', label: '定损单号（可空）' },
  { key: 'assessment_basis', label: '定损口径（已定损必填）' },
  { key: 'assessed_loss', label: '定损金额', type: 'number' },
  { key: 'status', label: '状态：已报案/已定损/已结案' },
]
const assessmentFields: FormField[] = [
  { key: 'assessment_no', label: '定损单号', required: true },
  { key: 'assessment_basis', label: '定损口径', required: true },
  { key: 'assessed_loss', label: '定损金额', type: 'number', required: true },
]

const formTitle = computed(() => {
  const titles: Record<string, string> = { create: '出险报案建档', backfill: '存量案件回填', assessment: '提交定损单' }
  return titles[formMode.value] ?? ''
})
const visibleFields = computed(() => {
  if (formMode.value === 'create') return createFields
  if (formMode.value === 'backfill') return backfillFields
  return assessmentFields
})

function resetForm() {
  Object.keys(form).forEach((key) => delete form[key])
  form.policy_version = '2026版'
}

function openCreate() {
  activeRow.value = null
  formMode.value = 'create'
  resetForm()
}

function openBackfill() {
  activeRow.value = null
  formMode.value = 'backfill'
  resetForm()
}

function openAssessment(row: Row) {
  detail.value = null
  activeRow.value = row
  formMode.value = 'assessment'
  resetForm()
}

function closeForm() {
  formMode.value = ''
  activeRow.value = null
}

async function submitForm() {
  errorMessage.value = ''
  try {
    const payload = Object.fromEntries(Object.entries(form).filter(([, value]) => value !== ''))
    if (formMode.value === 'create') {
      await postJson<ActionResponse>(ENDPOINT, payload)
    } else if (formMode.value === 'backfill') {
      await postJson<ActionResponse>(`${ENDPOINT}/backfill`, payload)
    } else if (activeRow.value) {
      await postJson<ActionResponse>(`${ENDPOINT}/${activeRow.value.id}/assessments`, payload)
    }
    closeForm()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交失败'
  }
}

async function closeClaim(row: Row) {
  errorMessage.value = ''
  try {
    const result = await postJson<ActionResponse>(`${ENDPOINT}/${row.id}/close`, {})
    detail.value = result.entry
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结案失败'
  }
}

async function viewDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('案件详情读取失败')
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '案件详情读取失败'
  }
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (status.value) query.set('status', status.value)
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok || !statsResponse.ok) throw new Error('保险理赔数据读取失败')
    const payload = await listResponse.json()
    const statPayload = await statsResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = statPayload.items ?? stats.value
    if (detail.value) {
      const updated = rows.value.find((item) => item.id === detail.value?.id)
      if (updated) detail.value = updated
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保险理赔数据读取失败'
  }
}

onMounted(reload)
</script>
