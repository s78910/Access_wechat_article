import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

test('快速开始导航项绑定到 GitHub quick start 文档外链', () => {
  assert.match(appVue, /\.nav-item\s*\{[\s\S]*?text-decoration:\s*none;/)
  assert.match(appVue, /type NavItem = \{[\s\S]*?href\?: string/)
  assert.match(
    appVue,
    /const quickStartUrl = 'https:\/\/github\.com\/yeximm\/Access_wechat_article\/blob\/main\/doc\/quick_start\.md'/,
  )
  assert.match(appVue, /\{ label: '快速开始', icon: 'fa-solid fa-book-open', page: null, href: quickStartUrl \}/)
  assert.match(appVue, /<a[\s\S]*?v-if="item\.href"[\s\S]*?:href="item\.href"[\s\S]*?target="_blank"[\s\S]*?rel="noopener noreferrer"/)
  assert.match(appVue, /<button[\s\S]*?v-else[\s\S]*?@click="selectPage\(item\.page\)"/)
})
