import { describe, expect, it } from 'vitest';

import {
  isEscalatedState,
  isSuspiciousLink,
  shouldGlowBanned,
  shouldHighlightTransition,
} from './graphCinematic';

describe('graphCinematic', () => {
  it('detects escalated states', () => {
    expect(isEscalatedState('RESTRICTED_WITHDRAWAL')).toBe(true);
    expect(isEscalatedState('UNDER_SURVEILLANCE')).toBe(true);
    expect(isEscalatedState('BANNED')).toBe(true);
    expect(isEscalatedState('NORMAL')).toBe(false);
  });

  it('highlights transition only when state changes to escalated', () => {
    expect(shouldHighlightTransition('NORMAL', 'RESTRICTED_WITHDRAWAL')).toBe(true);
    expect(shouldHighlightTransition('UNDER_SURVEILLANCE', 'BANNED')).toBe(true);
    expect(shouldHighlightTransition('NORMAL', 'NORMAL')).toBe(false);
    expect(shouldHighlightTransition(undefined, 'BANNED')).toBe(false);
  });

  it('glows when entering banned', () => {
    expect(shouldGlowBanned('UNDER_SURVEILLANCE', 'BANNED')).toBe(true);
    expect(shouldGlowBanned('BANNED', 'BANNED')).toBe(false);
    expect(shouldGlowBanned('NORMAL', 'UNDER_SURVEILLANCE')).toBe(false);
  });

  it('detects suspicious links by amount or count', () => {
    expect(isSuspiciousLink({ amount: 500_000, count: 1 })).toBe(true);
    expect(isSuspiciousLink({ amount: 100_000, count: 3 })).toBe(true);
    expect(isSuspiciousLink({ amount: 100_000, count: 1 })).toBe(false);
  });
});

