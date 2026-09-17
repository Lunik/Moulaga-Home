import type { Route } from './routing'

export function isRouteBeta(route: Route): boolean {
  // Keep this aligned with the explicit approvals recorded in ROADMAP.md's audit journal.
  return route.name !== 'dashboard' && route.name !== 'accounts' && route.name !== 'account' && route.name !== 'budget' && route.name !== 'wealth' && route.name !== 'documents'
}
