import { apiGet, apiPatch, apiPost, queryString } from './client'
import type { ProfileInput, ProfileOwnership, ProfileSession, UserProfile } from './types'

export const profileQueryKeys = {
  session: ['profile-session'] as const,
  publicList: ['profiles', 'public'] as const,
  adminList: ['profiles', 'admin'] as const,
  listPrefix: ['profiles'] as const,
}

/**
 * Central adapter for the profile/session API. Sessions are HTTP-only cookies;
 * the active profile must never be persisted by the browser.
 */
export const profilesApi = {
  list: (includeArchived = false) => apiGet<UserProfile[]>(
    `/profiles${queryString({ include_archived: includeArchived })}`,
  ),
  session: () => apiGet<ProfileSession>('/profiles/session'),
  openSession: (profileId: number, pin?: string) => apiPost<ProfileSession>(
    `/profiles/${profileId}/select`,
    pin ? { pin } : {},
  ),
  lock: () => apiPost<void>('/profiles/lock'),
  create: (input: ProfileInput) => apiPost<UserProfile>('/profiles', input),
  ownership: (profileId: number) => apiGet<ProfileOwnership>(`/profiles/${profileId}/ownership`),
  update: (profileId: number, input: Partial<ProfileInput>) => apiPatch<UserProfile>(
    `/profiles/${profileId}`,
    input,
  ),
}
