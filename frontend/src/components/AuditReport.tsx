import type { ArbitrationResult } from '../api';

function scoreColor(score: number): string {
  if (score <= 30) return 'bg-green-500';
  if (score <= 70) return 'bg-yellow-500';
  return 'bg-red-500';
}

function scoreBarColor(score: number): string {
  if (score <= 30) return 'bg-green-400';
  if (score <= 70) return 'bg-yellow-400';
  return 'bg-red-500';
}

export default function AuditReport({ analyses }: { analyses: ArbitrationResult[] }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 h-80 flex flex-col">
      <h3 className="text-sm font-semibold text-gray-700 mb-2 uppercase tracking-wide">AI監査レポート</h3>
      <div className="flex-1 overflow-y-auto space-y-3">
        {analyses.length === 0 && <p className="text-gray-400 text-center mt-8 text-sm">分析結果なし</p>}
        {analyses.map((a, i) => (
          <div key={i} className="border border-gray-100 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-bold text-white ${scoreColor(a.risk_score)}`}>
                  {a.risk_score}
                </span>
                <span className="text-sm font-semibold text-gray-800">{a.target_id}</span>
              </div>
              <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600 font-medium">
                {a.fraud_type}
              </span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-1.5 mb-2">
              <div
                className={`h-1.5 rounded-full ${scoreBarColor(a.risk_score)}`}
                style={{ width: `${a.risk_score}%` }}
              />
            </div>
            <p className="text-xs text-gray-700 leading-relaxed mb-1">{a.reasoning}</p>
            {a.evidence_event_ids.length > 0 && (
              <p className="text-xs text-gray-400">
                Evidence: {a.evidence_event_ids.join(', ')}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
