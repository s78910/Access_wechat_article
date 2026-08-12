import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

test('download options are compact and right aligned', () => {
  const match = appVue.match(/\.download-options\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(match?.groups?.body, 'missing .download-options style block')
  assert.match(match.groups.body, /justify-self:\s*end;/)
  assert.match(match.groups.body, /width:\s*min\(100%,\s*190px\);/)
})

test('task illustrations share the adjusted horizontal artwork offset', () => {
  const listArtRule = appVue.match(/\.task-art-list\s*\{(?<body>[\s\S]*?)\}/)
  const heartArtRule = appVue.match(/\.task-card-content \.task-art-heart\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(listArtRule?.groups?.body, 'missing .task-art-list style block')
  assert.ok(heartArtRule?.groups?.body, 'missing .task-card-content .task-art-heart style block')
  assert.match(listArtRule.groups.body, /transform:\s*translateX\(-14px\);/)
  assert.match(heartArtRule.groups.body, /transform:\s*translate\(-14px,\s*12px\);/)
})

test('获取指定内容把文章详情移到插画下方并在右侧加入离线归档', () => {
  assert.match(appVue, /mainTaskSelectionDefaultsApplied/)
  assert.match(appVue, /data_acquisition\.comment_collection\.enabled_by_default/)
  assert.match(appVue, /data_acquisition\.offline_cache\.enabled_by_default/)
  assert.match(appVue, /downloadSelections\.value\.offlineArchive\s*=\s*parseConfigSwitchValue/)
  assert.match(appVue, /downloadSelections\.value\.commentInfo\s*=\s*parseConfigSwitchValue/)
  assert.match(appVue, /const mandatoryDownloadOption = \{ key: 'articleDetail', label: '文章详情', locked: true \}/)
  assert.match(appVue, /const downloadOptions = \[\s*\{ key: 'offlineArchive', label: '离线归档', locked: false \}/)
  assert.match(appVue, /selections:\s*\{[\s\S]*offlineArchive: downloadSelections\.value\.offlineArchive/)

  const contentCardMatch = appVue.match(/<article class="task-card task-card-content panel">[\s\S]*?<\/article>/)
  assert.ok(contentCardMatch, '获取指定内容卡片应使用独立布局类')
  const contentCard = contentCardMatch[0]

  assert.match(contentCard, /<div class="task-art-column">[\s\S]*<img class="task-art task-art-heart"/)
  assert.match(contentCard, /class="\[\s*'download-option',\s*'article-detail-option'/)
  assert.match(contentCard, /mandatoryDownloadOption\.label/)
  assert.match(contentCard, /v-for="option in downloadOptions"[\s\S]*<span>\{\{ option\.label \}\}<\/span>/)
  assert.doesNotMatch(contentCard, /v-for="option in downloadOptions"[\s\S]*文章详情/)
})

test('获取指定内容插画下方按钮使用左侧独立布局区域', () => {
  const contentCardRule = appVue.match(/\.task-card-content\s*\{(?<body>[\s\S]*?)\}/)
  const artColumnRule = appVue.match(/\.task-art-column\s*\{(?<body>[\s\S]*?)\}/)
  const heartArtRule = appVue.match(/\.task-card-content \.task-art-heart\s*\{(?<body>[\s\S]*?)\}/)
  const articleDetailRule = appVue.match(/\.article-detail-option\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(contentCardRule?.groups?.body, 'missing .task-card-content style block')
  assert.ok(artColumnRule?.groups?.body, 'missing .task-art-column style block')
  assert.ok(heartArtRule?.groups?.body, 'missing .task-card-content .task-art-heart style block')
  assert.ok(articleDetailRule?.groups?.body, 'missing .article-detail-option style block')
  assert.match(contentCardRule.groups.body, /grid-template-columns:\s*118px minmax\(0, 1fr\);/)
  assert.match(contentCardRule.groups.body, /gap:\s*16px;/)
  assert.match(artColumnRule.groups.body, /grid-template-rows:\s*auto auto;/)
  assert.match(artColumnRule.groups.body, /align-content:\s*end;/)
  assert.match(artColumnRule.groups.body, /gap:\s*0;/)
  assert.match(heartArtRule.groups.body, /width:\s*112px;/)
  assert.match(heartArtRule.groups.body, /height:\s*112px;/)
  assert.match(heartArtRule.groups.body, /transform:\s*translate\(-14px,\s*12px\);/)
  assert.match(articleDetailRule.groups.body, /width:\s*184px;/)
  assert.match(articleDetailRule.groups.body, /min-height:\s*32px;/)
})
