import type { Category } from './api/types'

export function effectiveCategoryParentIds(categories: Category[]): Map<number, number | null> {
  const byId = new Map(categories.map((category) => [category.id, category]))
  const result = new Map<number, number | null>()
  for (const category of categories) {
    if (category.archived || category.kind !== 'expense') continue
    let parentId = category.parent_id
    const visited = new Set([category.id])
    while (parentId !== null) {
      if (visited.has(parentId)) {
        parentId = null
        break
      }
      visited.add(parentId)
      const parent = byId.get(parentId)
      if (!parent || parent.kind !== 'expense') {
        parentId = null
        break
      }
      if (!parent.archived) break
      parentId = parent.parent_id
    }
    result.set(category.id, parentId)
  }
  return result
}
