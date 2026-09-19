import type { ProfileReference, UserProfile } from './api/types'
import { Icon } from './ui'

export function ProfileOwnership({
  profiles,
  selectedIds,
  activeProfileId,
  onChange,
  title = 'Propriétaires',
  description = 'Choisissez les profils qui auront accès à cette ressource.',
}: {
  profiles: UserProfile[]
  selectedIds: number[]
  activeProfileId: number
  onChange: (ids: number[]) => void
  title?: string
  description?: string
}) {
  const selected = selectedIds.length > 0 ? selectedIds : [activeProfileId]
  const selectedProfiles = profiles.filter((profile) => selected.includes(profile.id))
  const availableProfiles = profiles.filter((profile) => profile.active)
  const isShared = selectedProfiles.length > 1

  return (
    <div className="ownership-field">
      <div className="ownership-heading">
        <strong>{title}</strong>
        <small>{description}</small>
      </div>
      <div className="ownership-options">
        {availableProfiles.map((profile) => {
          const checked = selected.includes(profile.id)
          return (
            <button
              aria-pressed={checked}
              className={`ownership-option${checked ? ' selected' : ''}`}
              key={profile.id}
              onClick={() => {
                if (checked && selected.length === 1) return
                onChange(checked
                  ? selected.filter((id) => id !== profile.id)
                  : [...selected, profile.id])
              }}
              type="button"
            >
              <ProfileBadge profile={profile} />
              <span aria-hidden="true" className="ownership-check">
                {checked && <Icon name="check" />}
              </span>
            </button>
          )
        })}
      </div>
      <div className={`ownership-summary${isShared ? ' shared' : ''}`}>
        <strong>{isShared ? `Partagé entre ${selectedProfiles.length} profils` : 'Personnel'}</strong>
        <span>
          {isShared
            ? `Répartition égale · 1/${selectedProfiles.length} par profil`
            : `Visible uniquement par ${selectedProfiles[0]?.name ?? ''}`}
        </span>
      </div>
    </div>
  )
}

export function ProfileBadge({ profile }: { profile: ProfileReference }) {
  return (
    <span className="profile-badge">
      <i style={{ background: profile.color }}>{profile.avatar || profile.name.slice(0, 1).toUpperCase()}</i>
      {profile.name}
    </span>
  )
}
