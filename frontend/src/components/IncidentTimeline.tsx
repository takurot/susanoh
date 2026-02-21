import type { ArbitrationResult, GameEvent, UserInfo } from '../api';
import { buildIncidentTimeline } from './incidentTimelineModel';

interface Props {
  users: UserInfo[];
  events: GameEvent[];
  analyses: ArbitrationResult[];
}

const STATE_BADGE: Record<string, string> = {
  NORMAL: 'bg-green-100 text-green-800',
  RESTRICTED_WITHDRAWAL: 'bg-yellow-100 text-yellow-800',
  UNDER_SURVEILLANCE: 'bg-orange-100 text-orange-800',
  BANNED: 'bg-red-100 text-red-800',
};

function stepClass(done: boolean): string {
  if (done) return 'bg-blue-50 text-blue-700 border-blue-200';
  return 'bg-gray-50 text-gray-400 border-gray-200';
}

export default function IncidentTimeline({ users, events, analyses }: Props) {
  const timeline = buildIncidentTimeline(users, events, analyses, 10);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Incident Timeline</h3>
        <span className="text-xs text-gray-400">{timeline.length} accounts</span>
      </div>

      {timeline.length === 0 ? (
        <p className="text-sm text-gray-400 py-6 text-center">No incident candidates</p>
      ) : (
        <div className="space-y-3 max-h-72 overflow-y-auto">
          {timeline.map((incident) => (
            <div key={incident.userId} className="rounded-lg border border-gray-100 p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="font-mono text-sm text-gray-800">{incident.userId}</div>
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATE_BADGE[incident.state] ?? 'bg-gray-100 text-gray-700'}`}>
                  {incident.state}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-1">
                {incident.steps.map((step) => (
                  <span
                    key={`${incident.userId}-${step.key}`}
                    className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border ${stepClass(step.done)}`}
                    title={step.detail}
                  >
                    <span>{step.done ? '●' : '○'}</span>
                    <span>{step.label}</span>
                    {step.detail && <span className="font-semibold">({step.detail})</span>}
                  </span>
                ))}
              </div>

              {incident.reasoning && (
                <p className="text-xs text-gray-600 mt-2 leading-relaxed">{incident.reasoning}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
