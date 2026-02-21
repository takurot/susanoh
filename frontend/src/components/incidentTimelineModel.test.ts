import { describe, expect, it } from 'vitest';

import type { ArbitrationResult, GameEvent, UserInfo } from '../api';
import { buildIncidentTimeline } from './incidentTimelineModel';

function makeEvent(overrides: Partial<GameEvent> = {}): GameEvent {
  return {
    event_id: 'evt_1',
    timestamp: '2026-02-21T12:00:00Z',
    event_type: 'TRADE',
    actor_id: 'user_mule_01',
    target_id: 'user_boss_01',
    action_details: {
      currency_amount: 250_000,
      item_id: 'itm_wood_stick_01',
      market_avg_price: 10,
    },
    context_metadata: {
      actor_level: 2,
      account_age_days: 1,
      recent_chat_log: 'Dで確認しました',
    },
    ...overrides,
  };
}

function makeAnalysis(overrides: Partial<ArbitrationResult> = {}): ArbitrationResult {
  return {
    target_id: 'user_boss_01',
    is_fraud: true,
    risk_score: 95,
    fraud_type: 'RMT_SMURFING',
    recommended_action: 'BANNED',
    reasoning: '短時間で複数送信者から集約',
    evidence_event_ids: ['evt_1'],
    confidence: 0.9,
    ...overrides,
  };
}

describe('buildIncidentTimeline', () => {
  it('builds full timeline steps for suspicious account', () => {
    const users: UserInfo[] = [{ user_id: 'user_boss_01', state: 'BANNED' }];
    const events: GameEvent[] = [makeEvent()];
    const analyses: ArbitrationResult[] = [makeAnalysis()];

    const result = buildIncidentTimeline(users, events, analyses, 10);

    expect(result).toHaveLength(1);
    expect(result[0].userId).toBe('user_boss_01');
    expect(result[0].state).toBe('BANNED');
    expect(result[0].steps).toEqual([
      { key: 'l1', label: 'L1 Flagged', done: true },
      { key: 'withdraw', label: 'Withdraw Restricted', done: true },
      { key: 'l2', label: 'L2 Analyzed', done: true, detail: 'risk 95' },
      { key: 'final', label: 'Final: BANNED', done: true },
    ]);
  });

  it('includes users that exist only in analyses', () => {
    const users: UserInfo[] = [];
    const events: GameEvent[] = [makeEvent({ target_id: 'user_layer_D' })];
    const analyses: ArbitrationResult[] = [makeAnalysis({ target_id: 'user_layer_D', recommended_action: 'UNDER_SURVEILLANCE', risk_score: 70 })];

    const result = buildIncidentTimeline(users, events, analyses, 10);

    expect(result).toHaveLength(1);
    expect(result[0].userId).toBe('user_layer_D');
    expect(result[0].state).toBe('UNDER_SURVEILLANCE');
  });
});
