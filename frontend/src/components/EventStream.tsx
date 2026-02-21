import { useRef, useEffect } from 'react';
import type { GameEvent } from '../api';

const STATE_DOT: Record<string, string> = {
  flagged: 'bg-red-500',
  normal: 'bg-green-400',
};
const SLANG_PATTERN = /振[り込]?込|D[でにて]確認|[0-9]+[kK千万]|りょ[。.]|PayPa[ly]|銀行|口座|送金|入金確認/;

function isSuspiciousEvent(event: GameEvent): boolean {
  if (typeof event.screened === 'boolean') return event.screened;
  if (event.triggered_rules && event.triggered_rules.length > 0) return true;

  const marketAvg = event.action_details.market_avg_price ?? 0;
  const r3 = marketAvg > 0 && event.action_details.currency_amount >= marketAvg * 100;
  const r4 = Boolean(event.context_metadata.recent_chat_log && SLANG_PATTERN.test(event.context_metadata.recent_chat_log));
  return r3 || r4;
}

export default function EventStream({ events }: { events: GameEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 h-80 flex flex-col">
      <h3 className="text-sm font-semibold text-gray-700 mb-2 uppercase tracking-wide">Real-Time Events</h3>
      <div className="flex-1 overflow-y-auto space-y-1 text-xs font-mono">
        {events.length === 0 && <p className="text-gray-400 text-center mt-8">No events</p>}
        {events.map((e) => {
          const isSus = isSuspiciousEvent(e);
          return (
            <div
              key={e.event_id}
              className={`flex items-center gap-2 px-2 py-1 rounded ${isSus ? 'bg-red-50 border border-red-200' : 'hover:bg-gray-50'}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isSus ? STATE_DOT.flagged : STATE_DOT.normal}`} />
              <span className="text-gray-400 w-16 flex-shrink-0">{e.event_id.slice(0, 12)}</span>
              <span className="text-gray-700 flex-shrink-0">{e.actor_id}</span>
              <span className="text-gray-400">→</span>
              <span className="text-gray-700 flex-shrink-0">{e.target_id}</span>
              <span className={`ml-auto font-semibold ${isSus ? 'text-red-600' : 'text-gray-600'}`}>
                {e.action_details.currency_amount.toLocaleString()}G
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
