import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')
const dataFilesPage = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('主服务页 Open Log Folder 按钮打开真实日志目录', () => {
  assert.match(appVue, /openRuntimePath/)
  assert.match(appVue, /openRuntimePath\('logDir'\)/)
  assert.match(appVue, /@click="handleOpenLogFolder"/)
  assert.doesNotMatch(appVue, /@click="handleOpenCurrentRuntimeLog"/)
})

test('数据档案页快速操作打开目录按钮打开项目 storages 目录', () => {
  assert.match(dataFilesPage, /openRuntimePath/)
  assert.match(dataFilesPage, /openRuntimePath\('storageDir'\)/)
  assert.match(dataFilesPage, /@click="handleOpenStorageDirectory"/)
})
