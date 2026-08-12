import assert from 'node:assert/strict'
import test from 'node:test'

import { calculatePagedTableRowHeight } from '../utils/pagedTableLayout.ts'

test('分页表格把表头之外的可用高度平均分给10条数据行', () => {
  assert.equal(calculatePagedTableRowHeight(414, 34, 10), 38)
  assert.equal(calculatePagedTableRowHeight(415, 34, 10), 38.1)
})

test('分页表格在尺寸无效时不生成负数或无穷行高', () => {
  assert.equal(calculatePagedTableRowHeight(0, 34, 10), 0)
  assert.equal(calculatePagedTableRowHeight(300, 34, 0), 0)
  assert.equal(calculatePagedTableRowHeight(Number.NaN, 34, 10), 0)
})
