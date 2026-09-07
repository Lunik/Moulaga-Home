const holdingAccountTypes: ReadonlySet<string> = new Set([
  // Preserve support for accounts created before the generic type was removed.
  'investment',
  'pea',
  'peg',
  'percol',
  'securities',
  'life_insurance',
  'wallet',
])

export function supportsHoldings(accountType: string): boolean {
  return holdingAccountTypes.has(accountType)
}
