import type { ArbitrationResult, GameEvent, UserInfo } from '../api';

const SLANG_PATTERN = /振[り込]?込|D[でにて]確認|[0-9]+[kK千万]|PayPa[ly]|銀行|口座|送金|入金確認/;
const SUSPICIOUS_AMOUNT = 100_000;

export interface IncidentTimelineStep {
  key: 'l1' | 'withdraw' | 'l2' | 'final';
  label: string;
  done: boolean;
  detail?: string;
}

export interface IncidentTimelineItem {
  userId: string;
  state: string;
  riskScore?: number;
  reasoning?: string;
  steps: IncidentTimelineStep[];
}

function stateRank(state: string): number {
  if (state === 'BANNED') return 3;
  if (state === 'UNDER_SURVEILLANCE') return 2;
  if (state === 'RESTRICTED_WITHDRAWAL') return 1;
  return 0;
}

function isSuspiciousEvent(event: GameEvent): boolean {
  const hasSlang = Boolean(event.context_metadata.recent_chat_log && SLANG_PATTERN.test(event.context_metadata.recent_chat_log));
  return event.action_details.currency_amount >= SUSPICIOUS_AMOUNT || hasSlang;
}

export function buildIncidentTimeline(
  users: UserInfo[],
  events: GameEvent[],
  analyses: ArbitrationResult[],
  limit = 10,
): IncidentTimelineItem[] {
  const usersById = new Map(users.map((user) => [user.user_id, user]));

  const latestAnalysisByUser = new Map<string, ArbitrationResult>();
  for (const analysis of analyses) {
    if (!latestAnalysisByUser.has(analysis.target_id)) {
      latestAnalysisByUser.set(analysis.target_id, analysis);
    }
  }

  const suspiciousEventTargets = new Set(
    events.filter(isSuspiciousEvent).map((event) => event.target_id),
  );

  const candidateIds = new Set<string>();
  for (const user of users) {
    if (user.state !== 'NORMAL') candidateIds.add(user.user_id);
  }
  for (const targetId of latestAnalysisByUser.keys()) {
    candidateIds.add(targetId);
  }
  for (const targetId of suspiciousEventTargets) {
    candidateIds.add(targetId);
  }

  const timeline = Array.from(candidateIds).map((userId) => {
    const user = usersById.get(userId);
    const latestAnalysis = latestAnalysisByUser.get(userId);
    const state = user?.state ?? latestAnalysis?.recommended_action ?? 'NORMAL';
    const hasL1 = suspiciousEventTargets.has(userId);
    const hasL2 = Boolean(latestAnalysis);
    const withdrawRestricted = state !== 'NORMAL';

    const steps: IncidentTimelineStep[] = [
      { key: 'l1', label: 'L1 Flagged', done: hasL1 },
      { key: 'withdraw', label: 'Withdraw Restricted', done: withdrawRestricted },
      {
        key: 'l2',
        label: 'L2 Analyzed',
        done: hasL2,
        detail: latestAnalysis ? `risk ${latestAnalysis.risk_score}` : undefined,
      },
      { key: 'final', label: `Final: ${state}`, done: state !== 'NORMAL' },
    ];

    return {
      userId,
      state,
      riskScore: latestAnalysis?.risk_score,
      reasoning: latestAnalysis?.reasoning,
      steps,
    };
  });

  timeline.sort((a, b) => {
    const stateDiff = stateRank(b.state) - stateRank(a.state);
    if (stateDiff !== 0) return stateDiff;

    const riskDiff = (b.riskScore ?? -1) - (a.riskScore ?? -1);
    if (riskDiff !== 0) return riskDiff;

    return a.userId.localeCompare(b.userId);
  });

  return timeline.slice(0, Math.max(0, limit));
}

