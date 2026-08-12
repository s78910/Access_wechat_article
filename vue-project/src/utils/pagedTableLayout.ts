/**
 * 计算固定分页表格的单行高度：表头占用固定空间，其余高度由当前页数据行平均分配。
 */
export function calculatePagedTableRowHeight(containerHeight: number, headerHeight: number, rowCount: number) {
  if (
    !Number.isFinite(containerHeight)
    || !Number.isFinite(headerHeight)
    || !Number.isFinite(rowCount)
    || containerHeight <= 0
    || headerHeight < 0
    || rowCount <= 0
  ) {
    return 0
  }

  const availableBodyHeight = Math.max(containerHeight - headerHeight, 0)
  return Math.floor((availableBodyHeight / rowCount) * 100) / 100
}
