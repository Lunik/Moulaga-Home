import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPatch } from '../api/client'
import { profileQueryKeys, profilesApi } from '../api/profiles'
import { PinKeypad } from '../PinKeypad'
import type {
  Household,
  HouseholdMember,
  ProfileSession,
  UserProfile,
} from '../api/types'
import {
  EmptyState,
  FormInput,
  Icon,
  Panel,
  StatusBadge,
  errorMessage,
  initials,
} from '../ui'

export function FamilyView({
  activeProfile,
  manageProfiles,
}: {
  activeProfile: UserProfile
  manageProfiles: () => void
}) {
  const queryClient = useQueryClient()
  const households = useQuery({
    queryKey: ['households'],
    queryFn: () => apiGet<Household[]>('/households'),
  })
  const activeHouseholdId = households.data?.[0]?.id ?? null
  const activeHousehold = households.data?.find((household) => household.id === activeHouseholdId)
  const members = activeHousehold?.members ?? []
  const errors = [households.error].filter(Boolean)
  const updateActiveProfile = (profile: UserProfile) => {
    queryClient.setQueryData<ProfileSession>(profileQueryKeys.session, { profile })
    queryClient.setQueriesData<UserProfile[]>({ queryKey: profileQueryKeys.listPrefix }, (current) => (
      current?.map((item) => item.id === profile.id ? profile : item)
    ))
  }

  if (!households.isLoading && (households.data?.length ?? 0) === 0) {
    return (
      <Panel title="Famille" subtitle="Le foyer de cette instance n’est pas encore disponible.">
        <EmptyState
          icon="family"
          title="Foyer indisponible"
          text="Le foyer technique est créé avec le premier profil."
        />
      </Panel>
    )
  }

  return (
    <div className="view-stack">
      <section className="section-intro">
        <div>
          <p>Ressources partagées du foyer.</p>
          <small>Profil actif : {activeProfile.name} · {activeProfile.role === 'admin' ? 'Administrateur' : 'Membre'}</small>
        </div>
      </section>

      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}

      {activeHouseholdId !== null && activeHousehold && (
        <>
          <FamilyHero
            canEdit={activeProfile.role === 'admin'}
            household={activeHousehold}
            memberCount={members.length}
            onUpdated={(updated) => {
              queryClient.setQueryData<Household[]>(['households'], (current) => (
                current?.map((item) => item.id === updated.id ? updated : item)
              ))
            }}
          />

          <section className="dashboard-grid">
            <ProfilePinSettings
              key={activeProfile.id}
              profile={activeProfile}
              onUpdated={updateActiveProfile}
            />
            <Panel
              title="Profils du foyer"
              subtitle={activeProfile.role === 'admin'
                ? 'Créez, modifiez ou archivez les profils de cette instance.'
                : 'Les profils sont gérés par un administrateur.'}
              action={activeProfile.role === 'admin' ? (
                <button className="secondary-button small-button" onClick={manageProfiles} type="button">
                  Gérer les profils
                </button>
              ) : undefined}
            >
              <div className="member-list">
                {members.map((member) => (
                  <div key={member.id}>
                    <span className="entity-avatar">{initials(member.name)}</span>
                    <span><strong>{member.name}</strong><small>Profil local</small></span>
                    <StatusBadge tone={member.role === 'owner' ? 'primary' : 'neutral'}>{roleLabel(member.role)}</StatusBadge>
                  </div>
                ))}
              </div>
            </Panel>
          </section>
        </>
      )}
    </div>
  )
}

function FamilyHero({
  canEdit,
  household,
  memberCount,
  onUpdated,
}: {
  canEdit: boolean
  household: Household
  memberCount: number
  onUpdated: (household: Household) => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(household.name)
  const mutation = useMutation({
    mutationFn: () => apiPatch<Household>(`/households/${household.id}`, { name }),
    onSuccess: (updated) => {
      onUpdated(updated)
      setEditing(false)
    },
  })

  if (editing) {
    return (
      <section className="family-hero">
        <span className="family-mark"><Icon name="family" /></span>
        <form
          className="compact-inline-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (name.trim().length > 0) mutation.mutate()
          }}
        >
          <FormInput
            aria-label="Nom du foyer"
            autoFocus
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
          <button className="primary-button icon-button" disabled={mutation.isPending} type="submit" aria-label="Enregistrer">
            <Icon name="check" />
          </button>
          <button
            className="text-button icon-button"
            onClick={() => {
              setName(household.name)
              setEditing(false)
              mutation.reset()
            }}
            type="button"
            aria-label="Annuler"
          >
            <Icon name="close" />
          </button>
          {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
        </form>
      </section>
    )
  }

  return (
    <section className="family-hero">
      <span className="family-mark"><Icon name="family" /></span>
      <div>
        <p className="eyebrow">Espace partagé</p>
        <h2>{household.name}</h2>
        <p>
          {memberCount} profil{memberCount === 1 ? '' : 's'}
        </p>
      </div>
      {canEdit && (
        <button
          className="secondary-button small-button"
          onClick={() => {
            setName(household.name)
            setEditing(true)
          }}
          type="button"
        >
          <Icon name="edit" /> Modifier le nom
        </button>
      )}
    </section>
  )
}

function ProfilePinSettings({
  profile,
  onUpdated,
}: {
  profile: UserProfile
  onUpdated: (profile: UserProfile) => void
}) {
  const [editing, setEditing] = useState(false)
  const [pin, setPin] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [pinStep, setPinStep] = useState<'choose' | 'confirm'>('choose')
  const closeEditor = () => {
    setEditing(false)
    setPin('')
    setConfirmation('')
    setPinStep('choose')
    updatePin.reset()
  }
  const updatePin = useMutation({
    mutationFn: (value: string | null) => profilesApi.update(profile.id, { pin: value }),
    onSuccess: (updated) => {
      onUpdated(updated)
      closeEditor()
    },
  })
  const matches = pin === confirmation
  const valid = confirmation.length >= 4 && matches

  return (
    <Panel
      className="profile-pin-panel"
      title="Sécurité de mon profil"
      subtitle="Vous seul choisissez et modifiez votre code PIN."
    >
      {!editing ? (
        <div className="profile-pin-overview">
          <span className={`profile-pin-icon${profile.has_pin ? ' active' : ''}`}>
            <Icon name="lock" />
          </span>
          <div className="profile-pin-status">
            <span>
              <strong>{profile.has_pin ? 'Profil protégé' : 'Profil sans protection'}</strong>
              <StatusBadge tone={profile.has_pin ? 'positive' : 'neutral'}>
                {profile.has_pin ? 'PIN activé' : 'Aucun PIN'}
              </StatusBadge>
            </span>
            <p>
              {profile.has_pin
                ? 'Le code sera demandé à chaque ouverture de ce profil.'
                : 'Ajoutez un code pour empêcher les autres membres d’ouvrir votre profil.'}
            </p>
          </div>
          <button
            className="secondary-button small-button"
            onClick={() => {
              updatePin.reset()
              setEditing(true)
            }}
            type="button"
          >
            <Icon name={profile.has_pin ? 'edit' : 'plus'} />
            {profile.has_pin ? 'Modifier' : 'Ajouter un PIN'}
          </button>
        </div>
      ) : (
        <form className="profile-pin-settings-form" onSubmit={(event) => {
          event.preventDefault()
          if (pinStep === 'choose' && pin.length >= 4) {
            setPinStep('confirm')
            return
          }
          if (valid) updatePin.mutate(pin)
        }}>
          <div className="profile-pin-editor-heading">
            <span className="profile-pin-icon active"><Icon name="lock" /></span>
            <span>
              <strong>
                {pinStep === 'choose'
                  ? profile.has_pin ? 'Remplacer mon code' : 'Créer mon code'
                  : 'Confirmer mon code'}
              </strong>
              <small>
                {pinStep === 'choose'
                  ? 'Choisissez entre 4 et 12 chiffres.'
                  : 'Saisissez une seconde fois le même code.'}
              </small>
            </span>
          </div>
          <div className="profile-pin-step-indicator" aria-label={`Étape ${pinStep === 'choose' ? 1 : 2} sur 2`}>
            <span className="active">1</span>
            <i />
            <span className={pinStep === 'confirm' ? 'active' : ''}>2</span>
          </div>
          <PinKeypad
            disabled={updatePin.isPending}
            label={pinStep === 'choose' ? 'Nouveau PIN' : 'Confirmation du PIN'}
            value={pinStep === 'choose' ? pin : confirmation}
            onChange={(value) => {
              if (pinStep === 'choose') setPin(value)
              else setConfirmation(value)
              updatePin.reset()
            }}
          />
          {pinStep === 'confirm' && confirmation.length >= pin.length && !matches && (
            <p className="form-error">Les deux codes PIN ne correspondent pas.</p>
          )}
          {pinStep === 'confirm' && matches && confirmation.length >= 4 && (
            <p className="profile-pin-success"><Icon name="check" /> Les deux codes correspondent.</p>
          )}
          {updatePin.error && <p className="form-error">{errorMessage(updatePin.error)}</p>}
          <div className="profile-pin-settings-footer">
            {profile.has_pin && (
              <button
                className="text-button destructive-button"
                disabled={updatePin.isPending}
                onClick={() => {
                  if (window.confirm('Retirer le PIN de votre profil ?')) updatePin.mutate(null)
                }}
                type="button"
              >
                Retirer mon PIN
              </button>
            )}
            <span className="profile-pin-settings-actions">
              <button
                className="text-button"
                onClick={() => {
                  if (pinStep === 'confirm') {
                    setPinStep('choose')
                    setConfirmation('')
                  } else {
                    closeEditor()
                  }
                }}
                type="button"
              >
                {pinStep === 'confirm' ? 'Modifier le code' : 'Annuler'}
              </button>
              <button
                className="primary-button"
                disabled={
                  updatePin.isPending
                  || (pinStep === 'choose' ? pin.length < 4 : !valid)
                }
                type="submit"
              >
                {updatePin.isPending
                  ? 'Enregistrement…'
                  : pinStep === 'choose' ? 'Continuer' : 'Enregistrer'}
              </button>
            </span>
          </div>
        </form>
      )}
    </Panel>
  )
}

function roleLabel(role: HouseholdMember['role']): string {
  return { owner: 'Propriétaire', admin: 'Administrateur', member: 'Membre', viewer: 'Lecture' }[role]
}
