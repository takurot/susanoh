const BASE = '/api/v1';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return { ...data, _status: res.status } as T;
  }
  return res.json();
}

export interface Stats {
  NORMAL: number;
  RESTRICTED_WITHDRAWAL: number;
  UNDER_SURVEILLANCE: number;
  BANNED: number;
  total_accounts: number;
  total_transitions: number;
  blocked_withdrawals: number;
  l1_flags: number;
  l2_analyses: number;
  total_events: number;
}

export interface TransitionLog {
  user_id: string;
  from_state: string;
  to_state: string;
  trigger: string;
  triggered_by_rule: string;
  timestamp: string;
  evidence_summary: string;
}

export interface GameEvent {
  event_id: string;
  timestamp: string;
  event_type: string;
  actor_id: string;
  target_id: string;
  screened?: boolean;
  triggered_rules?: string[];
  action_details: {
    currency_amount: number;
    item_id?: string;
    market_avg_price?: number;
  };
  context_metadata: {
    actor_level: number;
    account_age_days: number;
    recent_chat_log?: string;
  };
}

export interface ArbitrationResult {
  target_id: string;
  is_fraud: boolean;
  risk_score: number;
  fraud_type: string;
  recommended_action: string;
  reasoning: string;
  evidence_event_ids: string[];
  confidence: number;
}

export interface GraphNode {
  id: string;
  state: string;
  label: string;
}

export interface GraphLink {
  source: string;
  target: string;
  amount: number;
  count: number;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface UserInfo {
  user_id: string;
  state: string;
}

export interface ShowcaseResult {
  target_user: string;
  triggered_rules: string[];
  withdraw_status_code: number;
  latest_state: string;
  latest_risk_score?: number | null;
  latest_reasoning?: string | null;
  analysis_error?: string | null;
}

export const fetchStats = () => get<Stats>('/stats');
export const fetchTransitions = (limit = 50) => get<TransitionLog[]>(`/transitions?limit=${limit}`);
export const fetchAnalyses = (limit = 20) => get<ArbitrationResult[]>(`/analyses?limit=${limit}`);
export const fetchRecentEvents = (limit = 20) => get<GameEvent[]>(`/events/recent?limit=${limit}`);
export const fetchUsers = () => get<UserInfo[]>('/users');
export const fetchGraph = () => get<GraphData>('/graph');
export const triggerScenario = (name: string) => post<unknown>(`/demo/scenario/${name}`);
export const runShowcaseSmurfing = () => post<ShowcaseResult>('/demo/showcase/smurfing');
export const startDemo = () => post<unknown>('/demo/start');
export const stopDemo = () => post<unknown>('/demo/stop');
export const tryWithdraw = (userId: string, amount: number) =>
  post<{ status?: string; detail?: string; _status?: number }>('/withdraw', { user_id: userId, amount });
export const releaseUser = (userId: string) => post<unknown>(`/users/${userId}/release`);
