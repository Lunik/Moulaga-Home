import type { Route } from './routing'

// All pages have graduated out of beta; kept as a single hook so a future
// experimental route can flag itself here without touching call sites.
export function isRouteBeta(_route: Route): boolean {
  return false
}
