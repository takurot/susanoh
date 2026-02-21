import { useRef, useEffect } from 'react';
import type { GameEvent } from '../api';

const STATE_DOT: Record<string, string> = {
  flagged: 'bg-red-500',
  normal: 'bg-green-400',
};

export default function EventStream({ events }: { events: GameEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 h-80 flex flex-col">
      <h3 className="text-sm font-semibold text-gray-700 mb-2 uppercase tracking-wide">リアルタイムイベント</h3>
      <div className="flex-1 overflow-y-auto space-y-1 text-xs font-mono">
        {events.length === 0 && <p className="text-gray-400 text-center mt-8">イベントなし</p>}
        {events.map((e) => {
          const isSus = e.action_details.currency_amount >= 100_000 ||
            (e.context_metadata.recent_chat_log && /振[り込]?込|D[でにて]確認|[0-9]+[kK千万]|PayPa[ly]|銀行|口座|送金|入金確認/.test(e.context_metadata.recent_chat_log));
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
