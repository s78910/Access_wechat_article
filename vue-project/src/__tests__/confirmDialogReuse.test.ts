import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const componentPath = resolve(currentDir, '../components/ConfirmDialog.vue')
const settingsPageSource = readFileSync(resolve(currentDir, '../pages/SettingsPage.vue'), 'utf8')
const dataFilesPageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('通用确认弹窗组件承载证书安装和删除确认场景', () => {
  assert.ok(existsSync(componentPath), 'ConfirmDialog.vue should exist')
  const componentSource = readFileSync(componentPath, 'utf8')

  assert.match(componentSource, /type\s+ConfirmTone\s*=\s*'info'\s*\|\s*'warning'\s*\|\s*'danger'\s*\|\s*'success'/)
  assert.match(componentSource, /tone\?:\s*ConfirmTone/)
  assert.match(componentSource, /confirmIcon\?:\s*string/)
  assert.match(componentSource, /summaryItems:\s*ConfirmSummaryItem\[\]/)
  assert.match(componentSource, /role="dialog"/)
  assert.match(componentSource, /aria-modal="true"/)
})

test('设置页 CA 证书安装使用业务弹窗承载过程和结果', () => {
  assert.match(settingsPageSource, /caCertificateDialogVisible/)
  assert.match(settingsPageSource, /caCertificateDialogCanConfirmInstall/)
  assert.match(settingsPageSource, /@click="confirmInstallCaCertificate"/)
  assert.doesNotMatch(settingsPageSource, /<ConfirmDialog[\s\S]*@confirm="confirmInstallCaCertificate"/)
  assert.doesNotMatch(settingsPageSource, /window\.confirm/)
})

test('数据档案页删除确认迁移到通用确认弹窗并移除旧删除弹窗', () => {
  assert.match(dataFilesPageSource, /import ConfirmDialog from '\.\.\/components\/ConfirmDialog\.vue'/)
  assert.match(dataFilesPageSource, /<ConfirmDialog[\s\S]*tone="danger"/)
  assert.doesNotMatch(dataFilesPageSource, /DeleteConfirmDialog/)
})
