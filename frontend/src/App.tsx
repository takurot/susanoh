import { useState, useEffect, useCallback } from 'react';
import {
  fetchStats, fetchRecentEvents, fetchAnalyses, fetchGraph, fetchUsers,
  triggerScenario, startDemo, stopDemo,
} from './api';
import StatsCards from './components/StatsCards';
import EventStream from './components/EventStream';
import NetworkGraph from './components/NetworkGraph';
import AuditReport from './components/AuditReport';
import AccountTable from './components/AccountTable';

function usePolling<T>(fn: () => Promise<T>, interval: number): [T | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const refresh = useCallback(() => { fn().then(setData).catch(() => {}); }, [fn]);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, interval);
    return () => clearInterval(id);
  }, [refresh, interval]);
  return [data, refresh];
}

export default function App() {
  const [stats] = usePolling(fetchStats, 3000);
  const [events] = usePolling(fetchRecentEvents, 3000);
  const [analyses] = usePolling(fetchAnalyses, 3000);
  const [graph] = usePolling(fetchGraph, 5000);
  const [users, refreshUsers] = usePolling(fetchUsers, 5000);
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState('');

  const runScenario = async (name: string) => {
    setLoading(name);
    try { await triggerScenario(name); } catch {
      // Ignore transient API errors in demo control UI.
    }
    setLoading('');
  };

  const toggleStream = async () => {
    if (streaming) {
      try { await stopDemo(); } catch {
        // Ignore transient API errors in demo control UI.
        return;
      }
      setStreaming(false);
    } else {
      try { await startDemo(); } catch {
        // Ignore transient API errors in demo control UI.
        return;
      }
      setStreaming(true);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50 shadow-sm">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center">
              <span className="text-white font-bold text-sm">S</span>
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900 leading-tight">Susanoh</h1>
              <p className="text-xs text-gray-500">AI-Driven Game Economy Defense</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 mr-2">
              {stats ? `${stats.total_events} events processed` : '...'}
            </span>
            {/* Demo Controls */}
            <button
              onClick={() => runScenario('normal')}
              disabled={!!loading}
              className="px-3 py-1.5 rounded-lg bg-green-50 hover:bg-green-100 text-green-700 text-xs font-medium border border-green-200 disabled:opacity-50"
            >
              {loading === 'normal' ? '...' : 'Normal'}
            </button>
            <button
              onClick={() => runScenario('rmt-smurfing')}
              disabled={!!loading}
              className="px-3 py-1.5 rounded-lg bg-red-50 hover:bg-red-100 text-red-700 text-xs font-medium border border-red-200 disabled:opacity-50"
            >
              {loading === 'rmt-smurfing' ? '...' : 'Smurfing'}
            </button>
            <button
              onClick={() => runScenario('layering')}
              disabled={!!loading}
              className="px-3 py-1.5 rounded-lg bg-orange-50 hover:bg-orange-100 text-orange-700 text-xs font-medium border border-orange-200 disabled:opacity-50"
            >
              {loading === 'layering' ? '...' : 'Layering'}
            </button>
            <div className="w-px h-6 bg-gray-200 mx-1" />
            <button
              onClick={toggleStream}
              className={`px-4 py-1.5 rounded-lg text-xs font-medium border ${
                streaming
                  ? 'bg-gray-800 text-white border-gray-700 hover:bg-gray-700'
                  : 'bg-blue-500 text-white border-blue-500 hover:bg-blue-600'
              }`}
            >
              {streaming ? 'Stop Stream' : 'Start Stream'}
            </button>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="max-w-[1600px] mx-auto px-6 py-4 space-y-4">
        <StatsCards stats={stats} />
        <NetworkGraph data={graph} />
        <div className="grid grid-cols-2 gap-4">
          <EventStream events={events ?? []} />
          <AuditReport analyses={analyses ?? []} />
        </div>
        <AccountTable users={users ?? []} onRefresh={refreshUsers} />
      </main>
    </div>
  );
}
