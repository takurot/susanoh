import type { ArbitrationResult, GameEvent, UserInfo } from '../api';

const SLANG_PATTERN = /振[り込]?込|D[でにて]確認|[0-9]+[kK千万]|りょ[。.]|PayPa[ly]|銀行|口座|送金|入金確認/;
const AMOUNT_THRESHOLD = 1_000_000;
const TX_COUNT_THRESHOLD = 10;
const MARKET_AVG_MULTIPLIER = 100;

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

interface TargetWindowStats {
  totalAmount: number;
  txCount: number;
}

function stateRank(state: string): number {
  if (state === 'BANNED') return 3;
  if (state === 'UNDER_SURVEILLANCE') return 2;
  if (state === 'RESTRICTED_WITHDRAWAL') return 1;
  return 0;
}

function hasSlang(chatLog?: string): boolean {
  return Boolean(chatLog && SLANG_PATTERN.test(chatLog));
}

function buildTargetWindowStats(events: GameEvent[]): Map<string, TargetWindowStats> {
  const statsByTarget = new Map<string, TargetWindowStats>();

  // L1 is target-centric; aggregate by target_id to mirror backend semantics.
  for (const event of events) {
    const stats = statsByTarget.get(event.target_id) ?? { totalAmount: 0, txCount: 0 };
    stats.totalAmount += event.action_details.currency_amount;
    stats.txCount += 1;
    statsByTarget.set(event.target_id, stats);
  }

  return statsByTarget;
}

function fallbackScreened(event: GameEvent, statsByTarget: Map<string, TargetWindowStats>): boolean {
  const stats = statsByTarget.get(event.target_id) ?? { totalAmount: 0, txCount: 0 };
  const marketAvg = event.action_details.market_avg_price ?? 0;
  const r1 = stats.totalAmount >= AMOUNT_THRESHOLD;
  const r2 = stats.txCount >= TX_COUNT_THRESHOLD;
  const r3 = marketAvg > 0 && event.action_details.currency_amount >= marketAvg * MARKET_AVG_MULTIPLIER;
  const r4 = hasSlang(event.context_metadata.recent_chat_log);
  return r1 || r2 || r3 || r4;
}

function isSuspiciousEvent(event: GameEvent, statsByTarget: Map<string, TargetWindowStats>): boolean {
  if (typeof event.screened === 'boolean') return event.screened;
  if (event.triggered_rules && event.triggered_rules.length > 0) return true;
  if (hasSlang(event.context_metadata.recent_chat_log)) return true;
  return fallbackScreened(event, statsByTarget);
}

export function buildIncidentTimeline(
  users: UserInfo[],
  events: GameEvent[],
  analyses: ArbitrationResult[],
  limit = 10,
): IncidentTimelineItem[] {
  const usersById = new Map(users.map((user) => [user.user_id, user]));
  const statsByTarget = buildTargetWindowStats(events);

  const latestAnalysisByUser = new Map<string, ArbitrationResult>();
  for (const analysis of analyses) {
    if (!latestAnalysisByUser.has(analysis.target_id)) {
      latestAnalysisByUser.set(analysis.target_id, analysis);
    }
  }

  const suspiciousEventTargets = new Set(
    events
      .filter((event) => isSuspiciousEvent(event, statsByTarget))
      .map((event) => event.target_id),
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
