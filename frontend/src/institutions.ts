import type { Account } from './api/types'

export const institutionOptions: readonly string[] = [
  'ABN AMRO',
  'Amundi',
  'Banca Intesa Sanpaolo',
  'Banco Santander',
  'Bank of Ireland',
  'Banque Populaire',
  'Barclays',
  'BBVA',
  'BNP Paribas',
  'Boursobank',
  'Caisse d’Épargne',
  'CIC',
  'Commerzbank',
  'Crédit Agricole',
  'Crédit Mutuel',
  'Danske Bank',
  'Deutsche Bank',
  'Fortuneo',
  'Hello bank!',
  'HSBC',
  'ING',
  'KBC',
  'La Banque Postale',
  'LCL',
  'Lloyds Bank',
  'Monabanq',
  'N26',
  'NatWest',
  'Raiffeisen Bank',
  'Revolut',
  'Société Générale',
  'Trade Republic',
  'UniCredit',
  'Volkswagen Bank',
  'Wise',
] as const

export const regionalEntitySuggestions: Readonly<Record<string, readonly string[]>> = {
  'Banque Populaire': [
    'Alsace Lorraine Champagne',
    'Auvergne Rhône Alpes',
    'Bourgogne Franche-Comté',
    'Grand Ouest',
    'Méditerranée',
    'Occitane',
    'Rives de Paris',
    'Sud',
    'Val de France',
  ],
  'Caisse d’Épargne': [
    'Aquitaine Poitou-Charentes',
    'Bourgogne Franche-Comté',
    'Bretagne Pays de Loire',
    'Côte d’Azur',
    'Grand Est Europe',
    'Hauts de France',
    'Île-de-France',
    'Languedoc-Roussillon',
    'Loire Drôme Ardèche',
    'Loire-Centre',
    'Midi-Pyrénées',
    'Normandie',
    'Provence-Alpes-Corse',
    'Rhône Alpes',
  ],
  CIC: [
    'Est',
    'Lyonnaise de Banque',
    'Nord Ouest',
    'Ouest',
    'Sud Ouest',
  ],
  'Crédit Agricole': [
    'Alpes Provence',
    'Centre-est',
    'des Savoie',
    'Loire Haute-Loire',
    'Nord de France',
    'Provence Côte d’Azur',
    'Sud Rhône Alpes',
  ],
  'Crédit Mutuel': [
    'de Bretagne',
    'du Sud-Ouest',
  ],
}

export function accountInstitutionLabel(account: Account): string | null {
  const institution = account.institution?.trim()
  const regionalEntity = account.regional_entity?.trim()
  if (!institution) return null
  return regionalEntity ? `${institution} · ${regionalEntity}` : institution
}
