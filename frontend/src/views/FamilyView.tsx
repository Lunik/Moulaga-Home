import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost } from '../api/client'
import { profileQueryKeys, profilesApi } from '../api/profiles'
import { PinKeypad } from '../PinKeypad'
import type {
  GoalContribution,
  Household,
  HouseholdMember,
  ProfileSession,
  SharedGoal,
  UserProfile,
} from '../api/types'
import {
  EmptyState,
  FormInput,
  Icon,
  Panel,
  ProgressBar,
  StatusBadge,
  errorMessage,
  formatDate,
  initials,
  money,
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
  const goals = useQuery({
    queryKey: ['shared-goals', activeHouseholdId],
    queryFn: () => apiGet<SharedGoal[]>(`/households/${activeHouseholdId}/goals`),
    enabled: activeHouseholdId !== null,
  })
  const errors = [households.error, goals.error].filter(Boolean)
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
          <p>Objectifs et ressources partagés du foyer.</p>
          <small>Profil actif : {activeProfile.name} · {activeProfile.role === 'admin' ? 'Administrateur' : 'Membre'}</small>
        </div>
      </section>

      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}

      {activeHouseholdId !== null && (
        <>
          <section className="family-hero">
            <span className="family-mark"><Icon name="family" /></span>
            <div>
              <p className="eyebrow">Espace partagé</p>
              <h2>{activeHousehold?.name}</h2>
              <p>
                {members.length} profil{members.length === 1 ? '' : 's'} · objectifs communs
              </p>
            </div>
          </section>

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

          <Panel
            title="Objectifs partagés"
            subtitle="Suivez les contributions de chaque membre."
            action={(
              <GoalForm
                householdId={activeHouseholdId}
                onSaved={() => queryClient.invalidateQueries({ queryKey: ['shared-goals', activeHouseholdId] })}
              />
            )}
          >
            {(goals.data ?? []).length > 0 ? (
              <div className="goal-grid">
                {goals.data?.map((goal) => (
                  <GoalCard
                    goal={goal}
                    householdId={activeHouseholdId}
                    key={goal.id}
                    members={members}
                    onSaved={() => queryClient.invalidateQueries({ queryKey: ['shared-goals', activeHouseholdId] })}
                  />
                ))}
              </div>
            ) : (
              <EmptyState icon="target" text="Aucun objectif partagé." />
            )}
          </Panel>
        </>
      )}
    </div>
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

function GoalForm({
  householdId,
  onSaved,
}: {
  householdId: number
  onSaved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<SharedGoal>(
      `/households/${householdId}/goals`,
      { name, target_amount: target, current_amount: '0', due_date: null, account_id: null },
    ),
    onSuccess: async () => {
      setOpen(false)
      setName('')
      setTarget('')
      await onSaved()
    },
  })
  if (!open) return <button className="secondary-button small-button" type="button" onClick={() => setOpen(true)}><Icon name="plus" /> Objectif</button>
  return (
    <form className="compact-inline-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <FormInput aria-label="Nom de l'objectif" value={name} onChange={(event) => setName(event.target.value)} required />
      <FormInput aria-label="Montant cible" type="number" min="0.01" step="0.01" value={target} onChange={(event) => setTarget(event.target.value)} required />
      <button className="primary-button icon-button" type="submit" aria-label="Créer"><Icon name="check" /></button>
      <button className="text-button icon-button" type="button" aria-label="Annuler" onClick={() => setOpen(false)}><Icon name="close" /></button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function GoalCard({
  goal,
  householdId,
  members,
  onSaved,
}: {
  goal: SharedGoal
  householdId: number
  members: HouseholdMember[]
  onSaved: () => Promise<void>
}) {
  const [amount, setAmount] = useState('')
  const contributions = useQuery({
    queryKey: ['goal-contributions', goal.id],
    queryFn: () => apiGet<GoalContribution[]>(`/households/${householdId}/goals/${goal.id}/contributions`),
  })
  const mutation = useMutation({
    mutationFn: () => apiPost<GoalContribution>(
      `/households/${householdId}/goals/${goal.id}/contributions`,
      { amount, occurred_on: localDate(), note: null },
    ),
    onSuccess: async () => {
      setAmount('')
      await contributions.refetch()
      await onSaved()
    },
  })
  const percentage = Number(goal.target_amount) > 0
    ? (Number(goal.current_amount) / Number(goal.target_amount)) * 100
    : 0
  return (
    <article className="goal-card">
      <div className="goal-head">
        <span><i style={{ background: '#314ac8' }} /><strong>{goal.name}</strong></span>
        {goal.due_date && <small>{formatDate(goal.due_date)}</small>}
      </div>
      <div className="goal-values">
        <strong>{money(goal.current_amount)}</strong>
        <span>sur {money(goal.target_amount)}</span>
      </div>
      <ProgressBar value={percentage} color="#314ac8" />
      {(contributions.data ?? []).length > 0 && (
        <div className="contribution-summary">
          {contributions.data?.slice(0, 3).map((contribution) => (
            <span key={contribution.id}>
              {contribution.member_name ?? members.find((member) => member.id === contribution.member_id)?.name ?? 'Contribution'}
              {' '}<strong>{money(contribution.amount)}</strong>
            </span>
          ))}
        </div>
      )}
      <form className="goal-contribution-form" onSubmit={(event) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <FormInput type="number" min="0.01" step="0.01" placeholder="Contribution" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <button className="primary-button small-button" type="submit">Contribuer</button>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </article>
  )
}

function roleLabel(role: HouseholdMember['role']): string {
  return { owner: 'Propriétaire', admin: 'Administrateur', member: 'Membre', viewer: 'Lecture' }[role]
}

function localDate(): string {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}
