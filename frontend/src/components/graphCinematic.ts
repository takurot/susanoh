const ESCALATED_STATES = new Set([
  'RESTRICTED_WITHDRAWAL',
  'UNDER_SURVEILLANCE',
  'BANNED',
]);

export const SUSPICIOUS_LINK_AMOUNT = 500_000;
export const SUSPICIOUS_LINK_COUNT = 3;

export function isEscalatedState(state: string | undefined): boolean {
  return Boolean(state && ESCALATED_STATES.has(state));
}

export function shouldHighlightTransition(
  prevState: string | undefined,
  nextState: string | undefined,
): boolean {
  if (!prevState || !nextState) return false;
  if (prevState === nextState) return false;
  return isEscalatedState(nextState);
}

export function shouldGlowBanned(
  prevState: string | undefined,
  nextState: string | undefined,
): boolean {
  return prevState !== 'BANNED' && nextState === 'BANNED';
}

export function isSuspiciousLink(link: { amount: number; count: number }): boolean {
  return link.amount >= SUSPICIOUS_LINK_AMOUNT || link.count >= SUSPICIOUS_LINK_COUNT;
}

