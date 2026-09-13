import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { AttachmentManager, type AttachmentOwner } from '../AttachmentManager'
import { apiGet, apiPost, queryString } from '../api/client'
import type {
  DocumentCenter,
  DocumentItem,
  DocumentKind,
  DocumentResource,
} from '../api/types'
import type { DocumentsTab, Route } from '../routing'
import {
  EmptyState,
  FormInput,
  FormSelect,
  Icon,
  MetricCard,
  Modal,
  Panel,
  ProgressBar,
  StatusBadge,
  errorMessage,
  formatDate,
  formatFileSize,
  formatMonth,
} from '../ui'

const PAGE_SIZE = 12
const ALL_KINDS = 'all'

const documentTabs: Array<{
  id: DocumentsTab
  label: string
  icon: Parameters<typeof Icon>[0]['name']
}> = [
  { id: 'overview', label: "Vue d'ensemble", icon: 'grid' },
  { id: 'all', label: 'Tous les documents', icon: 'documents' },
  { id: 'missing', label: 'À compléter', icon: 'alert' },
]

const kindMeta: Record<DocumentKind, {
  label: string
  singular: string
  icon: Parameters<typeof Icon>[0]['name']
}> = {
  snapshot: { label: 'Relevés de compte', singular: 'Relevé', icon: 'accounts' },
  recurring: { label: 'Récurrents', singular: 'Récurrent', icon: 'recurring' },
  debt: { label: 'Dettes', singular: 'Dette', icon: 'debt' },
  real_estate: { label: 'Biens immobiliers', singular: 'Bien immobilier', icon: 'home' },
  work_contract: { label: 'Contrats de travail', singular: 'Contrat de travail', icon: 'briefcase' },
  payslip: { label: 'Fiches de paie', singular: 'Fiche de paie', icon: 'receipt' },
}

export function DocumentsView({
  tab,
  navigate,
}: {
  tab: DocumentsTab
  navigate: (route: Route) => void
}) {
  const center = useQuery({
    queryKey: ['documents'],
    queryFn: () => apiGet<DocumentCenter>('/documents'),
  })

  return (
    <div className="view-stack documents-view">
      <nav className="module-tabs budget-tabs documents-tabs" aria-label="Centre de documents">
        {documentTabs.map((item) => (
          <button
            className={tab === item.id ? 'active' : ''}
            type="button"
            key={item.id}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => navigate({ name: 'documents', tab: item.id })}
          >
            <Icon name={item.icon} />
            <span className="budget-tab-label">{item.label}</span>
            {item.id === 'missing' && (center.data?.stats.missing_resources ?? 0) > 0 && (
              <span className="documents-tab-count">{center.data?.stats.missing_resources}</span>
            )}
          </button>
        ))}
      </nav>

      {center.isLoading && <div className="loading-card">Indexation des documents…</div>}
      {center.error && (
        <div className="error-banner" role="alert">
          Impossible de charger les documents : {errorMessage(center.error)}
        </div>
      )}
      {center.data && tab === 'overview' && (
        <DocumentsOverview center={center.data} navigate={navigate} />
      )}
      {center.data && tab === 'all' && (
        <DocumentsLibrary center={center.data} onRefresh={() => center.refetch()} />
      )}
      {center.data && tab === 'missing' && (
        <MissingResources center={center.data} onRefresh={() => center.refetch()} />
      )}
    </div>
  )
}

function DocumentsOverview({
  center,
  navigate,
}: {
  center: DocumentCenter
  navigate: (route: Route) => void
}) {
  const coverage = percentage(center.stats.covered_resources, center.stats.total_resources)

  return (
    <>
      <section className="documents-hero">
        <div>
          <span className="documents-hero-icon"><Icon name="documents" /></span>
          <div>
            <p className="eyebrow">Centre documentaire local</p>
            <h2>Vos justificatifs, reliés à vos finances</h2>
            <p>
              Retrouvez les pièces jointes de vos relevés, revenus, contrats de travail,
              fiches de paie, dettes et biens sans dupliquer les fichiers.
            </p>
          </div>
        </div>
        <button
          className="primary-button"
          type="button"
          onClick={() => navigate({ name: 'documents', tab: 'missing' })}
        >
          <Icon name="attachment" /> Ajouter un document
        </button>
      </section>

      <section className="metric-grid" aria-label="Indicateurs documentaires">
        <MetricCard
          label="Documents"
          value={String(center.stats.total_documents)}
          detail={formatFileSize(center.stats.total_size)}
          icon="documents"
        />
        <MetricCard
          label="Ressources couvertes"
          value={`${coverage}%`}
          detail={`${center.stats.covered_resources} sur ${center.stats.total_resources}`}
          icon="check"
          tone="positive"
        />
        <MetricCard
          label="À compléter"
          value={String(center.stats.missing_resources)}
          detail="Sans pièce jointe"
          icon="alert"
          tone={center.stats.missing_resources > 0 ? 'negative' : 'positive'}
        />
        <MetricCard
          label="Stockage"
          value="Local"
          detail="Sous MOULAGA_DATA_DIR"
          icon="database"
        />
      </section>

      <section className="dashboard-grid documents-dashboard-grid">
        <Panel title="Couverture documentaire" subtitle="Par type de ressource">
          <div className="document-coverage-list">
            {center.kinds.map((kind) => {
              const value = percentage(kind.covered_resources, kind.total_resources)
              return (
                <div key={kind.kind}>
                  <span className="data-list-icon"><Icon name={kindMeta[kind.kind].icon} /></span>
                  <div>
                    <span>
                      <strong>{kind.label}</strong>
                      <small>{kind.covered_resources} / {kind.total_resources}</small>
                    </span>
                    <ProgressBar value={value} />
                  </div>
                  <strong>{value}%</strong>
                </div>
              )
            })}
          </div>
        </Panel>

        <Panel
          title="Ajouts récents"
          subtitle="Les cinq derniers fichiers"
          action={center.documents.length > 0 ? (
            <button
              className="text-button"
              type="button"
              onClick={() => navigate({ name: 'documents', tab: 'all' })}
            >
              Tout voir <Icon name="arrow" />
            </button>
          ) : undefined}
        >
          {center.documents.length > 0 ? (
            <div className="data-list document-recent-list">
              {center.documents.slice(0, 5).map((document) => (
                <a key={documentKey(document)} href={document.download_url}>
                  <span className="data-list-icon"><Icon name="documents" /></span>
                  <span>
                    <strong>{document.original_name}</strong>
                    <small>{document.resource_label} · {formatFileSize(document.size)}</small>
                  </span>
                  <Icon name="arrow" />
                </a>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="documents"
              title="Aucun document"
              text="Commencez par associer une pièce à une ressource."
            />
          )}
        </Panel>
      </section>
    </>
  )
}

function DocumentsLibrary({
  center,
  onRefresh,
}: {
  center: DocumentCenter
  onRefresh: () => Promise<unknown>
}) {
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<DocumentKind | typeof ALL_KINDS>(ALL_KINDS)
  const [selectedDocument, setSelectedDocument] = useState<DocumentItem | null>(null)
  const documents = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('fr-FR')
    return center.documents.filter((document) => (
      (kind === ALL_KINDS || document.kind === kind)
      && (
        !normalized
        || document.original_name.toLocaleLowerCase('fr-FR').includes(normalized)
        || document.resource_label.toLocaleLowerCase('fr-FR').includes(normalized)
        || document.resource_context.toLocaleLowerCase('fr-FR').includes(normalized)
      )
    ))
  }, [center.documents, kind, search])
  const selectedDocumentOwner = selectedDocument
    ? resourceOwner(selectedDocument)
    : null

  return (
    <>
      <DocumentFilters
        search={search}
        kind={kind}
        placeholder="Rechercher un fichier ou une ressource"
        onSearch={setSearch}
        onKind={setKind}
      />
      <Panel
        title="Bibliothèque"
        subtitle={`${documents.length} document${documents.length === 1 ? '' : 's'} · téléchargement direct`}
      >
        {documents.length > 0 ? (
          <div className="document-list">
            {documents.map((document) => (
              <article key={documentKey(document)}>
                <span className="document-file-icon"><Icon name="documents" /></span>
                <div className="document-list-copy">
                  <strong>{document.original_name}</strong>
                  <span>
                    <StatusBadge>{kindMeta[document.kind].singular}</StatusBadge>
                    <small>{document.resource_label} · {document.resource_context}</small>
                  </span>
                </div>
                <div className="document-list-meta">
                  <span>{formatReference(document.kind, document.reference)}</span>
                  <small>{formatFileSize(document.size)} · ajouté le {formatDate(document.created_at.slice(0, 10))}</small>
                </div>
                <div className="document-list-actions">
                  <a className="secondary-button small-button" href={document.download_url}>
                    Télécharger
                  </a>
                  {(document.kind === 'work_contract' || document.kind === 'payslip') && (
                    <button
                      className="secondary-button small-button"
                      type="button"
                      onClick={() => setSelectedDocument(document)}
                    >
                      <Icon name="attachment" /> Gérer
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon="search"
            title="Aucun résultat"
            text="Modifiez la recherche ou le type de document."
          />
        )}
      </Panel>

      {selectedDocument && selectedDocumentOwner && (
        <Modal
          title={`Gérer les documents de ${selectedDocument.resource_label}`}
          description={`${kindMeta[selectedDocument.kind].singular} · ${selectedDocument.resource_context}`}
          onClose={() => setSelectedDocument(null)}
        >
          <AttachmentManager
            owner={selectedDocumentOwner}
            readOnly={false}
            onChanged={onRefresh}
          />
        </Modal>
      )}
    </>
  )
}

function MissingResources({
  center,
  onRefresh,
}: {
  center: DocumentCenter
  onRefresh: () => Promise<unknown>
}) {
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<DocumentKind | typeof ALL_KINDS>(ALL_KINDS)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<DocumentResource | null>(null)
  const [showIgnored, setShowIgnored] = useState(false)
  const updateIgnored = useMutation({
    mutationFn: ({
      resource,
      ignored,
    }: {
      resource: DocumentResource
      ignored: boolean
    }) => apiPost<void>(
      `/documents/resources/${resource.kind}/${resource.resource_id}/ignored${queryString({ ignored })}`,
    ),
    onSuccess: onRefresh,
  })
  const resources = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('fr-FR')
    const source = showIgnored ? center.ignored_resources : center.resources_without_documents
    return source.filter((resource) => (
      (kind === ALL_KINDS || resource.kind === kind)
      && (
        !normalized
        || resource.label.toLocaleLowerCase('fr-FR').includes(normalized)
        || resource.context.toLocaleLowerCase('fr-FR').includes(normalized)
      )
    ))
  }, [center.ignored_resources, center.resources_without_documents, kind, search, showIgnored])
  const pageCount = Math.max(1, Math.ceil(resources.length / PAGE_SIZE))
  const visibleResources = resources.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => setPage(1), [kind, search, showIgnored])
  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const owner = selected ? resourceOwner(selected) : null

  return (
    <>
      <section className="missing-documents-intro">
        <span><Icon name="sparkle" /></span>
        <div>
          <strong>Une boîte de réception documentaire</strong>
          <p>
            Cette liste rassemble automatiquement chaque ressource sans pièce jointe.
            Ajoutez un fichier ici, ou ignorez les ressources qui ne nécessitent pas de document.
          </p>
        </div>
      </section>
      <DocumentFilters
        search={search}
        kind={kind}
        placeholder="Rechercher une ressource à compléter"
        onSearch={setSearch}
        onKind={setKind}
        action={(
          <button
            className="secondary-button documents-ignored-button"
            type="button"
            aria-pressed={showIgnored}
            onClick={() => setShowIgnored((current) => !current)}
          >
            <Icon name="archive" />
            Ignorés
            {center.ignored_resources.length > 0 && (
              <span>{center.ignored_resources.length}</span>
            )}
          </button>
        )}
      />
      <Panel
        title={showIgnored ? 'Ressources ignorées' : 'Ressources sans document'}
        subtitle={`${resources.length} élément${resources.length === 1 ? '' : 's'} ${showIgnored ? 'ignoré' : 'à compléter'}${showIgnored && resources.length !== 1 ? 's' : ''}`}
      >
        {visibleResources.length > 0 ? (
          <>
            <div className="missing-resource-list">
              {visibleResources.map((resource) => (
                <article key={resourceKey(resource)}>
                  <span className="data-list-icon"><Icon name={kindMeta[resource.kind].icon} /></span>
                  <div>
                    <span>
                      <strong>{resource.label}</strong>
                      <StatusBadge>{kindMeta[resource.kind].singular}</StatusBadge>
                    </span>
                    <small>{resource.context} · {formatReference(resource.kind, resource.reference)}</small>
                  </div>
                  <div className="missing-resource-actions">
                    {showIgnored ? (
                      <button
                        className="secondary-button small-button"
                        type="button"
                        disabled={updateIgnored.isPending}
                        onClick={() => updateIgnored.mutate({ resource, ignored: false })}
                      >
                        <Icon name="refresh" /> Restaurer
                      </button>
                    ) : (
                      <>
                        {resource.can_upload ? (
                          <button
                            className="primary-button small-button"
                            type="button"
                            onClick={() => setSelected(resource)}
                          >
                            <Icon name="attachment" /> Associer
                          </button>
                        ) : (
                          <StatusBadge tone="warning">Compte archivé</StatusBadge>
                        )}
                        <button
                          className="secondary-button small-button"
                          type="button"
                          disabled={updateIgnored.isPending}
                          onClick={() => updateIgnored.mutate({ resource, ignored: true })}
                        >
                          <Icon name="archive" /> Ignorer
                        </button>
                      </>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {pageCount > 1 && (
              <nav className="documents-pagination" aria-label="Pagination des ressources">
                <button
                  className="secondary-button small-button"
                  type="button"
                  disabled={page === 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                >
                  Précédent
                </button>
                <span>Page {page} sur {pageCount}</span>
                <button
                  className="secondary-button small-button"
                  type="button"
                  disabled={page === pageCount}
                  onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
                >
                  Suivant
                </button>
              </nav>
            )}
          </>
        ) : (
          <EmptyState
            icon={showIgnored ? 'archive' : center.stats.missing_resources === 0 ? 'check' : 'search'}
            title={showIgnored
              ? 'Aucune ressource ignorée'
              : center.stats.missing_resources === 0 ? 'Tout est classé' : 'Aucun résultat'}
            text={showIgnored
              ? 'Les ressources ignorées apparaîtront dans cette vue.'
              : center.stats.missing_resources === 0
                ? 'Chaque ressource possède un document ou a été ignorée.'
                : 'Modifiez la recherche ou le type de ressource.'}
          />
        )}
        {updateIgnored.error && (
          <p className="form-error">{errorMessage(updateIgnored.error)}</p>
        )}
      </Panel>

      {selected && owner && (
        <Modal
          title={`Associer un document à ${selected.label}`}
          description={`${kindMeta[selected.kind].singular} · ${selected.context}`}
          onClose={() => setSelected(null)}
        >
          <AttachmentManager
            owner={owner}
            readOnly={false}
            onChanged={async () => {
              await onRefresh()
              setSelected(null)
            }}
          />
        </Modal>
      )}
    </>
  )
}

function DocumentFilters({
  search,
  kind,
  placeholder,
  onSearch,
  onKind,
  action,
}: {
  search: string
  kind: DocumentKind | typeof ALL_KINDS
  placeholder: string
  onSearch: (value: string) => void
  onKind: (value: DocumentKind | typeof ALL_KINDS) => void
  action?: ReactNode
}) {
  return (
    <section className={`documents-toolbar${action ? ' has-action' : ''}`}>
      <label className="search-field">
        <Icon name="search" />
        <FormInput
          aria-label={placeholder}
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={placeholder}
        />
      </label>
      <FormSelect
        aria-label="Filtrer par type"
        value={kind}
        onChange={(event) => onKind(event.target.value as DocumentKind | typeof ALL_KINDS)}
      >
        <option value={ALL_KINDS}>Tous les types</option>
        {Object.entries(kindMeta).map(([value, meta]) => (
          <option key={value} value={value}>{meta.label}</option>
        ))}
      </FormSelect>
      {action}
    </section>
  )
}

function resourceOwner(
  resource: Pick<DocumentResource, 'kind' | 'resource_id' | 'account_id'>,
): AttachmentOwner | null {
  switch (resource.kind) {
    case 'snapshot':
      return resource.account_id === null
        ? null
        : { kind: 'snapshot', accountId: resource.account_id, snapshotId: resource.resource_id }
    case 'recurring':
      return { kind: 'recurring', seriesId: resource.resource_id }
    case 'debt':
      return { kind: 'debt', debtId: resource.resource_id }
    case 'real_estate':
      return { kind: 'real-estate', assetId: resource.resource_id }
    case 'work_contract':
      return { kind: 'work-contract', contractId: resource.resource_id }
    case 'payslip':
      return { kind: 'payslip', payslipId: resource.resource_id }
  }
}

function formatReference(kind: DocumentKind, reference: string | null): string {
  if (!reference) return 'Sans date'
  return kind === 'snapshot' || kind === 'payslip'
    ? formatMonth(reference)
    : formatDate(reference)
}

function percentage(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 100
}

function documentKey(document: DocumentItem): string {
  return `${document.kind}-${document.resource_id}-${document.id}`
}

function resourceKey(resource: DocumentResource): string {
  return `${resource.kind}-${resource.resource_id}`
}
