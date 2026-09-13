import { FormEvent, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload } from '../api/client'
import {
  AttachmentManager,
  AttachmentPicker,
  uploadOwnerAttachment,
} from '../AttachmentManager'
import type {
  PaySlip,
  PensionProfile,
  RecurringSeries,
  WorkContract,
  WorkSummary,
} from '../api/types'
import { routeHash, type Route, type WorkTab } from '../routing'
import {
  DatePicker,
  EmptyState,
  Field,
  FormInput,
  FormSelect,
  FormTextarea,
  Icon,
  LinkedEntityLink,
  MetricCard,
  Modal,
  Panel,
  ProgressBar,
  StatusBadge,
  chartTooltipStyle,
  compactMoney,
  errorMessage,
  formatDate,
  money,
} from '../ui'

export function WorkView({
  tab,
  navigate,
}: {
  tab: WorkTab
  navigate: (route: Route) => void
}) {
  const queryClient = useQueryClient()
  const tabsRef = useRef<HTMLElement>(null)

  // Queries
  const summary = useQuery({
    queryKey: ['work-summary'],
    queryFn: () => apiGet<WorkSummary>('/work/summary'),
  })
  const contracts = useQuery({
    queryKey: ['work-contracts'],
    queryFn: () => apiGet<WorkContract[]>('/work/contracts'),
  })
  const recurringSeries = useQuery({
    queryKey: ['recurring-series'],
    queryFn: () => apiGet<RecurringSeries[]>('/recurring'),
  })
  const payslips = useQuery({
    queryKey: ['work-payslips'],
    queryFn: () => apiGet<PaySlip[]>('/work/payslips'),
  })
  const pension = useQuery({
    queryKey: ['work-pension'],
    queryFn: () => apiGet<PensionProfile>('/work/pension'),
  })
  const firstError = [
    summary.error,
    contracts.error,
    recurringSeries.error,
    payslips.error,
    pension.error,
  ].find(Boolean)

  // State for Modals
  const [contractModal, setContractModal] = useState<{
    open: boolean
    contract?: WorkContract
  }>({ open: false })

  const [payslipModal, setPayslipModal] = useState<{
    open: boolean
    payslip?: PaySlip
  }>({ open: false })

  const [pensionModal, setPensionModal] = useState<boolean>(false)

  // Scroll active tab into view
  useLayoutEffect(() => {
    const tabs = tabsRef.current
    const activeTab = tabs?.querySelector<HTMLButtonElement>('.active')
    if (!tabs || !activeTab) return
    const tabsBounds = tabs.getBoundingClientRect()
    const activeBounds = activeTab.getBoundingClientRect()
    tabs.scrollLeft +=
      activeBounds.left -
      tabsBounds.left -
      (tabs.clientWidth - activeTab.clientWidth) / 2
  }, [tab])

  const refreshWorkData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['work-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['work-contracts'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-series'] }),
      queryClient.invalidateQueries({ queryKey: ['work-payslips'] }),
      queryClient.invalidateQueries({ queryKey: ['work-pension'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
    ])
  }

  // Contract Mutations
  const deleteContractMutation = useMutation({
    mutationFn: (id: number) => apiDelete(`/work/contracts/${id}`),
    onSuccess: refreshWorkData,
  })

  // PaySlip Mutations
  const deletePayslipMutation = useMutation({
    mutationFn: (id: number) => apiDelete(`/work/payslips/${id}`),
    onSuccess: refreshWorkData,
  })

  // Attachment Mutations
  const uploadAttachmentMutation = useMutation({
    mutationFn: ({ payslipId, file }: { payslipId: number; file: File }) => {
      const formData = new FormData()
      formData.append('file', file)
      return apiUpload(`/work/payslips/${payslipId}/attachments`, formData)
    },
    onSuccess: refreshWorkData,
  })

  const deleteAttachmentMutation = useMutation({
    mutationFn: (attachmentId: number) => apiDelete(`/work/attachments/${attachmentId}`),
    onSuccess: refreshWorkData,
  })

  // Chart Data preparation
  const remunerationChartData = useMemo(() => {
    if (!payslips.data || payslips.data.length === 0) return []
    return [...payslips.data]
      .reverse()
      .map((s) => ({
        period: s.period,
        brut: parseFloat(s.gross_salary),
        netAvantImpôt: parseFloat(s.net_before_tax),
        netAprèsImpôt: parseFloat(s.net_after_tax),
        primes: parseFloat(s.bonuses),
      }))
  }, [payslips.data])

  const packageBreakdownData = useMemo(() => {
    if (!payslips.data || payslips.data.length === 0) return []
    const latest = payslips.data[0]
    return [
      { name: 'Net après impôt', montant: parseFloat(latest.net_after_tax) },
      { name: 'Prélèvement à la source', montant: parseFloat(latest.pas_amount) },
      { name: 'Primes et intéressement', montant: parseFloat(latest.bonuses) + parseFloat(latest.employer_profit_sharing) },
      { name: 'Cotisations patronales', montant: parseFloat(latest.employer_contributions) },
    ]
  }, [payslips.data])

  const pensionProjectionData = useMemo(() => {
    const prof = pension.data
    const est = prof ? parseFloat(prof.estimated_monthly_pension) : 0
    const target = prof ? parseFloat(prof.target_monthly_income) : 0
    return [
      { age: '62 ans (décote)', pension: Math.round(est * 0.82), cible: target },
      { age: `${prof?.target_retirement_age ?? 64} ans (taux plein)`, pension: Math.round(est), cible: target },
      { age: '67 ans (automatique)', pension: Math.round(est * 1.1), cible: target },
    ]
  }, [pension.data])

  return (
    <div className="view-stack">
      {/* Sub-tabs header */}
      <nav className="module-tabs" aria-label="Travail" ref={tabsRef}>
        <button
          className={tab === 'overview' ? 'active' : ''}
          type="button"
          onClick={() => navigate({ name: 'work', tab: 'overview' })}
        >
          <Icon name="grid" /> Tableau de bord
        </button>
        <button
          className={tab === 'salary' ? 'active' : ''}
          type="button"
          onClick={() => navigate({ name: 'work', tab: 'salary' })}
        >
          <Icon name="receipt" /> Salaires et fiches de paie
        </button>
        <button
          className={tab === 'pension' ? 'active' : ''}
          type="button"
          onClick={() => navigate({ name: 'work', tab: 'pension' })}
        >
          <Icon name="target" /> Retraite
        </button>
      </nav>

      {firstError && (
        <div className="error-banner" role="alert">
          Impossible de charger les données Travail : {errorMessage(firstError)}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* SUB-TAB 1: Tableau de bord                                          */}
      {/* ------------------------------------------------------------------ */}
      {tab === 'overview' && (
        <div className="view-stack">
          <section className="metric-grid">
            <MetricCard
              label="Dernier net après impôt"
              value={money(summary.data?.latest_net_after_tax ?? '0.00')}
              detail={`${summary.data?.active_contracts_count ?? 0} contrat(s) actif(s)`}
              icon="receipt"
            />
            <MetricCard
              label="Cumul net imposable (YTD)"
              value={money(summary.data?.ytd_taxable_net ?? '0.00')}
              detail={`Net perçu : ${money(summary.data?.ytd_net_after_tax ?? '0.00')}`}
              icon="trend"
            />
            <MetricCard
              label="Taux moyen PAS"
              value={`${summary.data?.average_pas_rate ?? '0.00'} %`}
              detail="Prélèvement à la source"
              icon="grid"
            />
            <MetricCard
              label="Pension retraite estimée"
              value={money(summary.data?.estimated_pension ?? '0.00')}
              detail={`${summary.data?.validated_quarters ?? 0} / ${summary.data?.required_quarters ?? 172} trimestres`}
              icon="target"
            />
          </section>

          <section className="dashboard-grid">
            <Panel title="Évolution de la rémunération" subtitle="Brut vs Net avant et après impôt">
              {remunerationChartData.length > 0 ? (
                <div className="chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={remunerationChartData} margin={{ top: 12, right: 12, left: -8, bottom: 0 }}>
                      <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                      <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                      <Tooltip contentStyle={chartTooltipStyle} formatter={(val: unknown) => [money(Number(val ?? 0)), '']} />
                      <Legend />
                      <Line type="monotone" dataKey="brut" name="Brut" stroke="#8758f6" strokeWidth={2.2} dot={false} />
                      <Line type="monotone" dataKey="netAvantImpôt" name="Net avant impôt" stroke="#16c79a" strokeWidth={2.2} dot={false} />
                      <Line type="monotone" dataKey="netAprèsImpôt" name="Net après impôt" stroke="#615fff" strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  title="Aucune fiche de paie"
                  text="Ajoutez des fiches de paie dans l'onglet Salaires pour visualiser l'historique de votre rémunération."
                />
              )}
            </Panel>

            <Panel title="Détail du dernier bulletin" subtitle="Répartition de la fiche de paie récente">
              {packageBreakdownData.length > 0 ? (
                <div className="chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={packageBreakdownData} layout="vertical" margin={{ top: 8, right: 12, left: 12, bottom: 0 }}>
                      <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" horizontal={false} />
                      <XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                      <YAxis dataKey="name" type="category" width={130} axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
                      <Tooltip contentStyle={chartTooltipStyle} formatter={(val: unknown) => [money(Number(val ?? 0)), '']} />
                      <Bar dataKey="montant" name="Montant" fill="#16c79a" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  title="Données indisponibles"
                  text="Renseignez vos bulletins de paie pour analyser la structure de votre rémunération."
                />
              )}
            </Panel>
          </section>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* SUB-TAB 2: Salaires & Fiches de paie                                */}
      {/* ------------------------------------------------------------------ */}
      {tab === 'salary' && (
        <div className="view-stack">
          {/* Contracts Section */}
          <Panel
            title="Contrats de travail"
            subtitle="Emplois et postes enregistrés"
            className="work-action-panel"
            action={
              <button
                className="primary-button"
                type="button"
                onClick={() => setContractModal({ open: true })}
              >
                <Icon name="plus" /> Nouveau contrat
              </button>
            }
          >
            {contracts.data && contracts.data.length > 0 ? (
              <div className="work-contract-list">
                {contracts.data.map((contract) => {
                  const linkedSeries = recurringSeries.data?.find(
                    (series) => series.id === contract.recurring_series_id,
                  )
                  return (
                    <article className="work-contract-card" key={contract.id}>
                      <span className="work-list-icon"><Icon name="briefcase" /></span>
                      <span className="work-list-copy">
                        <span className="work-list-heading">
                          <strong>{contract.position}</strong>
                          <StatusBadge tone={contract.status === 'active' ? 'positive' : 'neutral'}>
                            {contract.status === 'active' ? 'Actif' : 'Terminé'}
                          </StatusBadge>
                          <StatusBadge>{contract.contract_type}</StatusBadge>
                        </span>
                        <small>
                          {contract.employer} ·{' '}
                          {contract.status === 'ended' && contract.end_date
                            ? `Du ${formatDate(contract.start_date)} au ${formatDate(contract.end_date)}`
                            : `Depuis le ${formatDate(contract.start_date)}`}
                        </small>
                        <small>
                          {contract.work_percentage}% · Versé sur {contract.payment_period_months} mois
                        </small>
                        {linkedSeries && (
                          <span className="linked-entities work-contract-links">
                            <LinkedEntityLink
                              href={routeHash({
                                name: 'budget',
                                tab: 'recurring',
                                focusId: linkedSeries.id,
                              })}
                              icon="recurring"
                              label={`Salaire récurrent : ${linkedSeries.label}`}
                            />
                          </span>
                        )}
                      </span>
                      <span className="work-list-value">
                        <strong>{money(contract.gross_annual_salary)}</strong>
                        <small>brut annuel</small>
                      </span>
                      <span className="row-actions">
                        <button
                          className="icon-action"
                          type="button"
                          aria-label={`Modifier le contrat ${contract.position}`}
                          onClick={() => setContractModal({ open: true, contract })}
                        >
                          <Icon name="edit" />
                        </button>
                        <button
                          className="icon-action destructive-button"
                          type="button"
                          aria-label={`Supprimer le contrat ${contract.position}`}
                          disabled={deleteContractMutation.isPending}
                          onClick={() => {
                            if (window.confirm(`Supprimer le contrat chez ${contract.employer} ?`)) {
                              deleteContractMutation.mutate(contract.id)
                            }
                          }}
                        >
                          <Icon name="trash" />
                        </button>
                      </span>
                    </article>
                  )
                })}
              </div>
            ) : (
              <EmptyState
                title="Aucun contrat de travail"
                text="Ajoutez votre premier contrat de travail pour suivre votre salaire contractuel."
              />
            )}
          </Panel>

          {/* PaySlips Section */}
          <Panel
            title="Fiches de paie"
            subtitle="Historique des bulletins de paie et justificatifs"
            className="work-action-panel"
            action={
              <button
                className="primary-button"
                type="button"
                onClick={() => setPayslipModal({ open: true })}
              >
                <Icon name="plus" /> Ajouter une fiche de paie
              </button>
            }
          >
            {payslips.data && payslips.data.length > 0 ? (
              <div className="work-payslip-list">
                {payslips.data.map((payslip) => (
                  <article className="work-payslip-card" key={payslip.id}>
                    <span className="work-list-icon"><Icon name="receipt" /></span>
                    <span className="work-list-copy">
                      <span className="work-list-heading">
                        <strong>{payslip.period}</strong>
                        <StatusBadge>PAS {payslip.pas_rate}%</StatusBadge>
                      </span>
                      <small>
                        Brut {money(payslip.gross_salary)} · Net imposable {money(payslip.taxable_net)}
                      </small>
                      <small>
                        Net avant impôt {money(payslip.net_before_tax)}
                        {Number(payslip.bonuses) + Number(payslip.employer_profit_sharing) > 0
                          ? ` · Primes ${money(Number(payslip.bonuses) + Number(payslip.employer_profit_sharing))}`
                          : ''}
                      </small>
                      <span className="work-attachments">
                        {payslip.attachments.map((attachment) => (
                          <span className="work-attachment" key={attachment.id}>
                            <a href={`/api/work/attachments/${attachment.id}`} target="_blank" rel="noreferrer">
                              <Icon name="attachment" /> {attachment.original_name}
                            </a>
                            <button
                              className="icon-action destructive-button"
                              type="button"
                              aria-label={`Supprimer ${attachment.original_name}`}
                              onClick={() => deleteAttachmentMutation.mutate(attachment.id)}
                            >
                              <Icon name="trash" />
                            </button>
                          </span>
                        ))}
                        <label className="secondary-button work-attachment-upload">
                          <Icon name="attachment" />
                          <span>Joindre</span>
                          <input
                            type="file"
                            className="work-file-input"
                            onChange={(event) => {
                              const file = event.target.files?.[0]
                              if (file) uploadAttachmentMutation.mutate({ payslipId: payslip.id, file })
                            }}
                          />
                        </label>
                      </span>
                    </span>
                    <span className="work-list-value">
                      <strong>{money(payslip.net_after_tax)}</strong>
                      <small>net versé</small>
                    </span>
                    <span className="row-actions">
                      <button
                        className="icon-action"
                        type="button"
                        aria-label={`Modifier la fiche ${payslip.period}`}
                        onClick={() => setPayslipModal({ open: true, payslip })}
                      >
                        <Icon name="edit" />
                      </button>
                      <button
                        className="icon-action destructive-button"
                        type="button"
                        aria-label={`Supprimer la fiche ${payslip.period}`}
                        disabled={deletePayslipMutation.isPending}
                        onClick={() => {
                          if (window.confirm(`Supprimer la fiche de paie du ${payslip.period} ?`)) {
                            deletePayslipMutation.mutate(payslip.id)
                          }
                        }}
                      >
                        <Icon name="trash" />
                      </button>
                    </span>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                title="Aucune fiche de paie enregistrée"
                text="Conservez vos fiches de paie pour analyser vos revenus réels et vos cotisations."
              />
            )}
          </Panel>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* SUB-TAB 3: Retraite                                                 */}
      {/* ------------------------------------------------------------------ */}
      {tab === 'pension' && (
        <div className="view-stack">
          <Panel
            title="Profil et compteur de trimestres"
            subtitle="Vos droits acquis à la retraite"
            className="work-action-panel"
            action={
              <button
                className="primary-button"
                type="button"
                onClick={() => setPensionModal(true)}
              >
                <Icon name="edit" /> Paramètres retraite
              </button>
            }
          >
            <section className="metric-grid">
              <MetricCard
                label="Trimestres validés"
                value={`${pension.data?.validated_quarters ?? 0} / ${pension.data?.required_quarters ?? 172}`}
                detail="Pour le taux plein"
                icon="target"
              />
              <MetricCard
                label="Âge de départ cible"
                value={`${pension.data?.target_retirement_age ?? 64} ans`}
                detail={`Né(e) en ${pension.data?.birth_year ?? 1990}`}
                icon="calendar"
              />
              <MetricCard
                label="Pension mensuelle estimée"
                value={money(pension.data?.estimated_monthly_pension ?? '0.00')}
                detail="Au taux plein"
                icon="trend"
              />
              <MetricCard
                label="Revenu mensuel cible"
                value={money(pension.data?.target_monthly_income ?? '0.00')}
                detail="Objectif souhaité"
                icon="wealth"
              />
            </section>

            <div className="work-quarter-progress">
              <p>
                Avancement des trimestres cotisés
              </p>
              <ProgressBar
                value={Math.round(
                  ((pension.data?.validated_quarters ?? 0) / (pension.data?.required_quarters ?? 172)) * 100,
                )}
              />
            </div>

            {pension.data?.notes && (
              <div className="work-pension-notes">
                <strong>Notes :</strong> {pension.data.notes}
              </div>
            )}
          </Panel>

          <Panel title="Projection de la pension selon l'âge de départ" subtitle="Simulation indicative de vos revenus à la retraite">
            <div className="chart-container tall-chart">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={pensionProjectionData} margin={{ top: 12, right: 12, left: -8, bottom: 0 }}>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="age" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(val: unknown) => [money(Number(val ?? 0)), '']} />
                  <Legend />
                  <Area type="monotone" dataKey="pension" name="Pension estimée" stroke="#4f46e5" fill="#4f46e5" fillOpacity={0.2} />
                  <Area type="monotone" dataKey="cible" name="Objectif souhaité" stroke="#16c79a" fill="#16c79a" fillOpacity={0.1} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* MODALS                                                             */}
      {/* ------------------------------------------------------------------ */}

      {/* Contract Modal */}
      {contractModal.open && (
        <ContractFormModal
          contract={contractModal.contract}
          recurringSeries={recurringSeries.data ?? []}
          onClose={() => setContractModal({ open: false })}
          onSuccess={() => {
            setContractModal({ open: false })
            refreshWorkData()
          }}
        />
      )}

      {/* PaySlip Modal */}
      {payslipModal.open && (
        <PaySlipFormModal
          payslip={payslipModal.payslip}
          contracts={contracts.data ?? []}
          onClose={() => setPayslipModal({ open: false })}
          onSuccess={() => {
            setPayslipModal({ open: false })
            refreshWorkData()
          }}
        />
      )}

      {/* Pension Modal */}
      {pensionModal && (
        <PensionFormModal
          profile={pension.data}
          onClose={() => setPensionModal(false)}
          onSuccess={() => {
            setPensionModal(false)
            refreshWorkData()
          }}
        />
      )}
    </div>
  )
}

function ContractFormModal({
  contract,
  recurringSeries,
  onClose,
  onSuccess,
}: {
  contract?: WorkContract
  recurringSeries: RecurringSeries[]
  onClose: () => void
  onSuccess: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const formId = contract ? `work-contract-edit-${contract.id}` : 'work-contract-create'
  const salarySeries = recurringSeries.filter(
    (series) =>
      series.recurring_type === 'salary'
      || series.id === contract?.recurring_series_id,
  )
  const mutation = useMutation({
    mutationFn: (data: Partial<WorkContract>) =>
      contract ? apiPatch(`/work/contracts/${contract.id}`, data) : apiPost('/work/contracts', data),
    onSuccess,
    onError: (err) => setError(errorMessage(err)),
  })

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    const fd = new FormData(e.currentTarget)
    mutation.mutate({
      employer: String(fd.get('employer') || ''),
      position: String(fd.get('position') || ''),
      contract_type: String(fd.get('contract_type') || 'CDI'),
      start_date: String(fd.get('start_date') || ''),
      end_date: fd.get('end_date') ? String(fd.get('end_date')) : null,
      gross_annual_salary: String(fd.get('gross_annual_salary') || '0.00'),
      work_percentage: Number(fd.get('work_percentage') || 100),
      payment_period_months: Number(fd.get('payment_period_months') || 12),
      recurring_series_id: fd.get('recurring_series_id') ? Number(fd.get('recurring_series_id')) : null,
      status: (String(fd.get('status') || 'active')) as 'active' | 'ended',
      notes: fd.get('notes') ? String(fd.get('notes')) : null,
    })
  }

  return (
    <Modal
      title={contract ? 'Modifier le contrat' : 'Nouveau contrat de travail'}
      description="Le contrat décrit votre rémunération. Le salaire lié reste la série récurrente de référence dans Budget."
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form work-modal-form" id={formId} onSubmit={handleSubmit}>
        {error && <p className="form-error work-modal-wide">{error}</p>}

        <Field label="Employeur / Entreprise">
          <FormInput name="employer" defaultValue={contract?.employer ?? ''} required />
        </Field>

        <Field label="Intitulé du poste">
          <FormInput name="position" defaultValue={contract?.position ?? ''} required />
        </Field>

        <div className="work-form-grid">
          <Field label="Type de contrat">
            <FormSelect name="contract_type" defaultValue={contract?.contract_type ?? 'CDI'}>
              <option value="CDI">CDI</option>
              <option value="CDD">CDD</option>
              <option value="Freelance">Freelance / Indépendant</option>
              <option value="Fonctionnaire">Fonctionnaire</option>
              <option value="Autre">Autre</option>
            </FormSelect>
          </Field>

          <Field label="Temps de travail (%)">
            <FormInput type="number" name="work_percentage" defaultValue={contract?.work_percentage ?? 100} min={10} max={100} />
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Date de début">
            <DatePicker name="start_date" defaultValue={contract?.start_date ?? ''} required />
          </Field>

          <Field label="Date de fin (facultatif)">
            <DatePicker name="end_date" defaultValue={contract?.end_date ?? ''} />
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Salaire brut annuel (€)">
            <FormInput type="number" step="0.01" name="gross_annual_salary" defaultValue={contract?.gross_annual_salary ?? '0.00'} />
          </Field>

          <Field label="Période de paiement">
            <FormSelect name="payment_period_months" defaultValue={contract?.payment_period_months ?? 12}>
              {[12, 13, 14, 15].map((months) => (
                <option key={months} value={months}>{months} mois</option>
              ))}
            </FormSelect>
          </Field>

          <Field label="Salaire récurrent lié">
            <FormSelect name="recurring_series_id" defaultValue={contract?.recurring_series_id ?? ''}>
              <option value="">Aucun salaire récurrent</option>
              {salarySeries.map((series) => (
                <option key={series.id} value={series.id}>
                  {series.label} ({frequencyLabel(series.frequency)})
                </option>
              ))}
            </FormSelect>
          </Field>

          <Field label="Statut">
            <FormSelect name="status" defaultValue={contract?.status ?? 'active'}>
              <option value="active">Actif</option>
              <option value="ended">Terminé</option>
            </FormSelect>
          </Field>
        </div>

        <Field label="Notes / Avantages">
          <FormTextarea name="notes" defaultValue={contract?.notes ?? ''} placeholder="Ex : forfait jours, PEE, mutuelle…" rows={3} />
        </Field>

      </form>
    </Modal>
  )
}

function PaySlipFormModal({
  payslip,
  contracts,
  onClose,
  onSuccess,
}: {
  payslip?: PaySlip
  contracts: WorkContract[]
  onClose: () => void
  onSuccess: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [attachment, setAttachment] = useState<File | null>(null)
  const createdPayslipId = useRef<number | null>(null)
  const formId = payslip ? `work-payslip-edit-${payslip.id}` : 'work-payslip-create'
  const mutation = useMutation({
    mutationFn: async (data: Partial<PaySlip>) => {
      const existingId = payslip?.id ?? createdPayslipId.current
      const savedPayslip = await (existingId
        ? apiPatch<PaySlip>(`/work/payslips/${existingId}`, data)
        : apiPost<PaySlip>('/work/payslips', data))
      createdPayslipId.current = savedPayslip.id
      if (!payslip && attachment) {
        await uploadOwnerAttachment(
          { kind: 'payslip', payslipId: savedPayslip.id },
          attachment,
        )
      }
      return savedPayslip
    },
    onSuccess,
    onError: (err) => setError(errorMessage(err)),
  })

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    const fd = new FormData(e.currentTarget)
    const contractId = fd.get('contract_id') ? Number(fd.get('contract_id')) : null
    mutation.mutate({
      contract_id: contractId,
      period: String(fd.get('period') || ''),
      gross_salary: String(fd.get('gross_salary') || '0.00'),
      taxable_net: String(fd.get('taxable_net') || '0.00'),
      net_before_tax: String(fd.get('net_before_tax') || '0.00'),
      pas_rate: String(fd.get('pas_rate') || '0.00'),
      pas_amount: String(fd.get('pas_amount') || '0.00'),
      net_after_tax: String(fd.get('net_after_tax') || '0.00'),
      bonuses: String(fd.get('bonuses') || '0.00'),
      employer_contributions: String(fd.get('employer_contributions') || '0.00'),
      employer_profit_sharing: String(fd.get('employer_profit_sharing') || '0.00'),
      notes: fd.get('notes') ? String(fd.get('notes')) : null,
    })
  }

  return (
    <Modal
      title={payslip ? 'Modifier la fiche de paie' : 'Nouvelle fiche de paie'}
      description="Ces montants servent uniquement à l'analyse salariale et ne modifient aucun solde de compte."
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form work-modal-form" id={formId} onSubmit={handleSubmit}>
        {error && <p className="form-error work-modal-wide">{error}</p>}

        <div className="work-form-grid">
          <Field label="Période">
            <DatePicker type="month" name="period" defaultValue={payslip?.period ?? ''} required />
          </Field>

          <Field label="Contrat associé">
            <FormSelect name="contract_id" defaultValue={payslip?.contract_id ?? ''}>
              <option value="">-- Aucun --</option>
              {contracts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.employer} ({c.position})
                </option>
              ))}
            </FormSelect>
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Salaire brut (€)">
            <FormInput type="number" step="0.01" name="gross_salary" defaultValue={payslip?.gross_salary ?? '0.00'} />
          </Field>

          <Field label="Net imposable (€)">
            <FormInput type="number" step="0.01" name="taxable_net" defaultValue={payslip?.taxable_net ?? '0.00'} />
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Net avant impôt (€)">
            <FormInput type="number" step="0.01" name="net_before_tax" defaultValue={payslip?.net_before_tax ?? '0.00'} />
          </Field>

          <Field label="Taux PAS (%)">
            <FormInput type="number" step="0.01" name="pas_rate" defaultValue={payslip?.pas_rate ?? '0.00'} />
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Montant PAS retenu (€)">
            <FormInput type="number" step="0.01" name="pas_amount" defaultValue={payslip?.pas_amount ?? '0.00'} />
          </Field>

          <Field label="Net après impôt perçu (€)">
            <FormInput type="number" step="0.01" name="net_after_tax" defaultValue={payslip?.net_after_tax ?? '0.00'} required />
          </Field>
        </div>

        <div className="work-form-grid work-form-grid-three">
          <Field label="Primes & Variables (€)">
            <FormInput type="number" step="0.01" name="bonuses" defaultValue={payslip?.bonuses ?? '0.00'} />
          </Field>

          <Field label="Cotisations patronales (€)">
            <FormInput type="number" step="0.01" name="employer_contributions" defaultValue={payslip?.employer_contributions ?? '0.00'} />
          </Field>

          <Field label="Intéressement (€)">
            <FormInput type="number" step="0.01" name="employer_profit_sharing" defaultValue={payslip?.employer_profit_sharing ?? '0.00'} />
          </Field>
        </div>

        <Field label="Remarques">
          <FormTextarea name="notes" defaultValue={payslip?.notes ?? ''} placeholder="Notes ou faits marquants du mois…" rows={3} />
        </Field>

        <div className="modal-attachment-field work-modal-wide">
          {payslip ? (
            <AttachmentManager
              owner={{ kind: 'payslip', payslipId: payslip.id }}
              readOnly={false}
            />
          ) : (
            <AttachmentPicker
              file={attachment}
              onChange={setAttachment}
              disabled={mutation.isPending}
            />
          )}
        </div>
      </form>
    </Modal>
  )
}

function PensionFormModal({
  profile,
  onClose,
  onSuccess,
}: {
  profile?: PensionProfile
  onClose: () => void
  onSuccess: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const formId = 'work-pension-profile'
  const mutation = useMutation({
    mutationFn: (data: Partial<PensionProfile>) => apiPut('/work/pension', data),
    onSuccess,
    onError: (err) => setError(errorMessage(err)),
  })

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    const fd = new FormData(e.currentTarget)
    mutation.mutate({
      birth_year: Number(fd.get('birth_year') || 1990),
      target_retirement_age: Number(fd.get('target_retirement_age') || 64),
      validated_quarters: Number(fd.get('validated_quarters') || 0),
      required_quarters: Number(fd.get('required_quarters') || 172),
      estimated_monthly_pension: String(fd.get('estimated_monthly_pension') || '0.00'),
      target_monthly_income: String(fd.get('target_monthly_income') || '0.00'),
      notes: fd.get('notes') ? String(fd.get('notes')) : null,
    })
  }

  return (
    <Modal
      title="Paramètres du profil retraite"
      description="Renseignez les estimations de votre relevé de carrière pour suivre votre progression."
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form work-modal-form" id={formId} onSubmit={handleSubmit}>
        {error && <p className="form-error work-modal-wide">{error}</p>}

        <div className="work-form-grid">
          <Field label="Année de naissance">
            <FormInput type="number" name="birth_year" defaultValue={profile?.birth_year ?? 1990} required />
          </Field>

          <Field label="Âge de départ cible">
            <FormInput type="number" name="target_retirement_age" defaultValue={profile?.target_retirement_age ?? 64} required />
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Trimestres validés">
            <FormInput type="number" name="validated_quarters" defaultValue={profile?.validated_quarters ?? 40} required />
          </Field>

          <Field label="Trimestres requis">
            <FormInput type="number" name="required_quarters" defaultValue={profile?.required_quarters ?? 172} required />
          </Field>
        </div>

        <div className="work-form-grid">
          <Field label="Pension estimée au taux plein (€)">
            <FormInput type="number" step="0.01" name="estimated_monthly_pension" defaultValue={profile?.estimated_monthly_pension ?? '0.00'} />
          </Field>

          <Field label="Revenu mensuel cible (€)">
            <FormInput type="number" step="0.01" name="target_monthly_income" defaultValue={profile?.target_monthly_income ?? '0.00'} />
          </Field>
        </div>

        <Field label="Notes / Référence du relevé">
          <FormTextarea name="notes" defaultValue={profile?.notes ?? ''} placeholder="Ex : selon le RIS 2026…" rows={3} />
        </Field>

      </form>
    </Modal>
  )
}

function frequencyLabel(frequency: RecurringSeries['frequency']): string {
  return {
    weekly: 'hebdomadaire',
    monthly: 'mensuel',
    quarterly: 'trimestriel',
    yearly: 'annuel',
  }[frequency]
}
