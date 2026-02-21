import type { Stats } from '../api';

const cards = [
  { key: 'total_events', label: 'Total Events', color: 'bg-blue-500' },
  { key: 'l1_flags', label: 'L1 Flags', color: 'bg-yellow-500' },
  { key: 'l2_analyses', label: 'L2 Analyses', color: 'bg-orange-500' },
  { key: 'BANNED', label: 'Bans', color: 'bg-red-600' },
  { key: 'blocked_withdrawals', label: 'Blocked Withdrawals', color: 'bg-purple-600' },
] as const;

export default function StatsCards({ stats }: { stats: Stats | null }) {
  return (
    <div className="grid grid-cols-5 gap-3">
      {cards.map((c) => (
        <div key={c.key} className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2.5 h-2.5 rounded-full ${c.color}`} />
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{c.label}</span>
          </div>
          <p className="text-3xl font-bold text-gray-900">
            {stats ? (stats as unknown as Record<string, number>)[c.key] ?? 0 : '—'}
          </p>
        </div>
      ))}
    </div>
  );
}
