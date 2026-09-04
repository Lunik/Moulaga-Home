export interface SavingsBalanceSnapshot {
  period: string
  balance: number
}

export interface SavingsProjection {
  year: number
  referenceBalance: number
  referencePeriod: string | null
  estimatedInterest: number
  projectedBalance: number
}

export function calculateSavingsProjection(
  snapshots: readonly SavingsBalanceSnapshot[],
  accountBalance: number,
  annualRate: number,
  year: number,
): SavingsProjection {
  const yearStart = `${year}-01`
  const yearEnd = `${year}-12`
  const eligibleSnapshots = snapshots
    .filter((snapshot) => (
      /^\d{4}-(0[1-9]|1[0-2])$/.test(snapshot.period)
      && snapshot.period <= yearEnd
      && Number.isFinite(snapshot.balance)
    ))
    .sort((left, right) => left.period.localeCompare(right.period))
  const latestSnapshot = eligibleSnapshots.at(-1)
  const referenceBalance = nonNegative(latestSnapshot?.balance ?? accountBalance)
  const currentYearSnapshots = eligibleSnapshots.filter(
    (snapshot) => snapshot.period >= yearStart,
  )
  const balanceByMonth = new Map(
    currentYearSnapshots.map((snapshot) => [
      Number(snapshot.period.slice(5, 7)),
      nonNegative(snapshot.balance),
    ]),
  )
  const priorSnapshot = eligibleSnapshots
    .filter((snapshot) => snapshot.period < yearStart)
    .at(-1)
  let carriedBalance = priorSnapshot
    ? nonNegative(priorSnapshot.balance)
    : currentYearSnapshots.length === 0
      ? referenceBalance
      : 0
  let weightedBalance = 0

  for (let month = 1; month <= 12; month += 1) {
    carriedBalance = balanceByMonth.get(month) ?? carriedBalance
    weightedBalance += carriedBalance
  }

  const normalizedRate = Number.isFinite(annualRate) ? Math.max(0, annualRate) : 0
  const estimatedInterest = roundMoney(weightedBalance * normalizedRate / 100 / 12)

  return {
    year,
    referenceBalance,
    referencePeriod: latestSnapshot?.period ?? null,
    estimatedInterest,
    projectedBalance: roundMoney(referenceBalance + estimatedInterest),
  }
}

function nonNegative(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0
}

function roundMoney(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100
}
