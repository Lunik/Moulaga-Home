import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import type { AppSettings, MerchantIdentity } from '../api/types'
import { FormInput, FormSelect, Icon, Panel, errorMessage, formatDate } from '../ui'

export function SettingsView() {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiGet<AppSettings>('/preferences'),
  })
  const update = useMutation({
    mutationFn: (payload: Partial<AppSettings>) => apiPatch<AppSettings>('/preferences', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  if (settings.isLoading) return <div className="loading-card">Chargement des paramètres…</div>
  if (settings.error) return <div className="error-banner">{errorMessage(settings.error)}</div>
  if (!settings.data) return null

  return (
    <div className="view-stack settings-stack">
      {update.error && <div className="error-banner">{errorMessage(update.error)}</div>}
      <AppearanceSettings settings={settings.data} onSave={(payload) => update.mutate(payload)} />
      <BudgetCycleSettings settings={settings.data} saving={update.isPending} onSave={(payload) => update.mutate(payload)} />
      <PrivacySettings settings={settings.data} onSave={(payload) => update.mutate(payload)} />
      <AiSettings settings={settings.data} onSave={(payload) => update.mutate(payload)} />
    </div>
  )
}

function AppearanceSettings({
  settings,
  onSave,
}: {
  settings: AppSettings
  onSave: (payload: Partial<AppSettings>) => void
}) {
  return (
    <Panel title="Apparence" subtitle="Personnalisez uniquement la présentation de cette instance.">
      <div className="setting-list">
        <SettingRow label="Thème">
          <SegmentedControl
            value={settings.theme}
            options={[
              ['light', 'Clair'],
              ['dark', 'Sombre'],
              ['system', 'Système'],
            ]}
            onChange={(value) => onSave({ theme: value as AppSettings['theme'] })}
          />
        </SettingRow>
        <SettingRow label="Langue">
          <SegmentedControl
            value={settings.language}
            options={[
              ['fr', 'FR'],
              ['en', 'EN'],
              ['de', 'DE'],
              ['es', 'ES'],
            ]}
            onChange={(value) => onSave({ language: value as AppSettings['language'] })}
          />
        </SettingRow>
        <SettingRow label="Format de date">
          <SegmentedControl
            value={settings.date_format}
            options={[
              ['localized', 'Localisé'],
              ['day-month-year', 'JJ-MM-AAAA'],
              ['YYYY-MM-DD', 'AAAA-MM-JJ'],
            ]}
            onChange={(value) => onSave({ date_format: value as AppSettings['date_format'] })}
          />
        </SettingRow>
        <SettingRow label="Style de navigation">
          <SegmentedControl
            value={settings.navigation_style}
            options={[
              ['sidebar', 'Actuel'],
              ['compact', 'Compact'],
              ['topbar', 'Barre haute'],
            ]}
            onChange={(value) => onSave({ navigation_style: value as AppSettings['navigation_style'] })}
          />
        </SettingRow>
      </div>
    </Panel>
  )
}

function BudgetCycleSettings({
  settings,
  saving,
  onSave,
}: {
  settings: AppSettings
  saving: boolean
  onSave: (payload: Partial<AppSettings>) => void
}) {
  const [day, setDay] = useState(String(settings.budget_cycle_start_day))
  useEffect(() => setDay(String(settings.budget_cycle_start_day)), [settings.budget_cycle_start_day])
  const bounds = cycleBounds(settings.budget_cycle_start_day)

  return (
    <Panel title="Jour de paie" subtitle="Votre cycle budgétaire démarre ce jour-là chaque mois, pas forcément le 1er.">
      <form className="cycle-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        onSave({ budget_cycle_start_day: Number(day) })
      }}>
        <label>
          <span>Jour de début du cycle</span>
          <FormInput type="number" min="1" max="28" value={day} onChange={(event) => setDay(event.target.value)} required />
        </label>
        <button className="primary-button" type="submit" disabled={saving}>Enregistrer</button>
      </form>
      <p className="setting-hint">Cycle en cours : du {formatDate(bounds.start)} au {formatDate(bounds.end)}</p>
    </Panel>
  )
}

function PrivacySettings({
  settings,
  onSave,
}: {
  settings: AppSettings
  onSave: (payload: Partial<AppSettings>) => void
}) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const merchants = useQuery({
    queryKey: ['merchants'],
    queryFn: () => apiGet<MerchantIdentity[]>('/merchants'),
    enabled: settings.local_merchant_identities,
  })
  return (
    <Panel title="Identités visuelles locales" subtitle="Utilise uniquement des monogrammes et couleurs stockés localement. Aucun marchand n'est envoyé à un service externe.">
      <ToggleRow
        label="Afficher les identités visuelles"
        detail="Désactivé par défaut et purement cosmétique."
        checked={settings.local_merchant_identities}
        onChange={(checked) => onSave({ local_merchant_identities: checked })}
      />
      {settings.local_merchant_identities && (
        <div className="merchant-settings">
          <div className="merchant-settings-head">
            <p>Les motifs sont comparés localement aux libellés des transactions.</p>
            <button className="secondary-button small-button" type="button" onClick={() => setShowForm((current) => !current)}>
              <Icon name="plus" />Identité
            </button>
          </div>
          {showForm && (
            <MerchantForm
              onCancel={() => setShowForm(false)}
              onSaved={async () => {
                await queryClient.invalidateQueries({ queryKey: ['merchants'] })
                setShowForm(false)
              }}
            />
          )}
          {merchants.error && <p className="form-error">{errorMessage(merchants.error)}</p>}
          <div className="merchant-list">
            {merchants.data?.map((merchant) => (
              <MerchantRow
                key={merchant.id}
                merchant={merchant}
                onDeleted={() => queryClient.invalidateQueries({ queryKey: ['merchants'] })}
              />
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}

function MerchantForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const [label, setLabel] = useState('')
  const [pattern, setPattern] = useState('')
  const [monogram, setMonogram] = useState('')
  const [color, setColor] = useState('#615fff')
  const mutation = useMutation({
    mutationFn: () => apiPost<MerchantIdentity>('/merchants', { label, pattern, monogram, color }),
    onSuccess: onSaved,
  })
  return (
    <form className="compact-feature-form merchant-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <FormInput aria-label="Libellé" placeholder="Libellé local" value={label} onChange={(event) => setLabel(event.target.value)} required />
      <FormInput aria-label="Motif" placeholder="Motif à reconnaître" value={pattern} onChange={(event) => setPattern(event.target.value)} required />
      <FormInput aria-label="Monogramme" placeholder="ABC" maxLength={4} value={monogram} onChange={(event) => setMonogram(event.target.value)} />
      <FormInput className="color-input" aria-label="Couleur" type="color" value={color} onChange={(event) => setColor(event.target.value)} />
      <button className="primary-button small-button" type="submit">Créer</button>
      <button className="text-button" type="button" onClick={onCancel}>Annuler</button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function MerchantRow({
  merchant,
  onDeleted,
}: {
  merchant: MerchantIdentity
  onDeleted: () => Promise<void>
}) {
  const remove = useMutation({
    mutationFn: () => apiDelete(`/merchants/${merchant.id}`),
    onSuccess: onDeleted,
  })
  return (
    <div>
      <span className="merchant-mark" style={{ background: merchant.color }}>{merchant.monogram || merchant.label.slice(0, 2).toUpperCase()}</span>
      <span><strong>{merchant.label}</strong><small>Motif : {merchant.pattern}</small></span>
      <button className="icon-action" type="button" aria-label="Supprimer" onClick={() => remove.mutate()}><Icon name="trash" /></button>
      {remove.error && <span className="form-error">{errorMessage(remove.error)}</span>}
    </div>
  )
}

function AiSettings({
  settings,
  onSave,
}: {
  settings: AppSettings
  onSave: (payload: Partial<AppSettings>) => void
}) {
  return (
    <Panel title="Catégorisation privée" subtitle="Le moteur fonctionne localement après les règles déterministes. Aucune donnée bancaire ne quitte l'instance.">
      <ToggleRow
        label="Activer les suggestions locales"
        detail="Ne traite que les transactions restées non catégorisées."
        checked={settings.private_categorization_enabled}
        onChange={(checked) => onSave({
          private_categorization_enabled: checked,
          private_categorization_mode: checked && settings.private_categorization_mode === 'off'
            ? 'suggest'
            : settings.private_categorization_mode,
        })}
      />
      <div className={`ai-options ${settings.private_categorization_enabled ? '' : 'disabled'}`}>
        <label className="field">
          <span>Comportement des suggestions</span>
          <FormSelect
            disabled={!settings.private_categorization_enabled}
            value={settings.private_categorization_mode}
            onChange={(event) => onSave({ private_categorization_mode: event.target.value as AppSettings['private_categorization_mode'] })}
          >
            <option value="suggest">Toujours proposer</option>
            <option value="auto">Appliquer si le moteur est sûr</option>
            <option value="off">Désactivé</option>
          </FormSelect>
        </label>
        <label className="range-field">
          <span>
            <strong>Seuil de confiance</strong>
            <output>{Math.round(settings.private_categorization_confidence * 100)}%</output>
          </span>
          <FormInput
            type="range"
            min="0.5"
            max="1"
            step="0.05"
            disabled={!settings.private_categorization_enabled}
            value={settings.private_categorization_confidence}
            onChange={(event) => onSave({ private_categorization_confidence: Number(event.target.value) })}
          />
          <small>En dessous, le moteur laisse une suggestion au lieu d'appliquer la catégorie.</small>
        </label>
      </div>
    </Panel>
  )
}

function SettingRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="setting-row">
      <strong>{label}</strong>
      {children}
    </div>
  )
}

function SegmentedControl({
  value,
  options,
  onChange,
}: {
  value: string
  options: Array<[string, string]>
  onChange: (value: string) => void
}) {
  return (
    <div className="segmented-control">
      {options.map(([optionValue, label]) => (
        <button
          className={value === optionValue ? 'active' : ''}
          type="button"
          key={optionValue}
          onClick={() => onChange(optionValue)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function ToggleRow({
  label,
  detail,
  checked,
  onChange,
}: {
  label: string
  detail: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="toggle-row">
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <FormInput type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="toggle-visual"><Icon name="check" /></span>
    </label>
  )
}

function cycleBounds(startDay: number): { start: string; end: string } {
  const today = new Date()
  const startsThisMonth = today.getDate() >= startDay
  const start = new Date(today.getFullYear(), today.getMonth() - (startsThisMonth ? 0 : 1), startDay)
  const end = new Date(start.getFullYear(), start.getMonth() + 1, startDay - 1)
  return { start: localIsoDate(start), end: localIsoDate(end) }
}

function localIsoDate(date: Date): string {
  const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return adjusted.toISOString().slice(0, 10)
}
