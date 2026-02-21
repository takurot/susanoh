import { useState } from 'react';
import type { UserInfo } from '../api';
import { tryWithdraw, releaseUser } from '../api';

const STATE_BADGE: Record<string, string> = {
  NORMAL: 'bg-green-100 text-green-800',
  RESTRICTED_WITHDRAWAL: 'bg-yellow-100 text-yellow-800',
  UNDER_SURVEILLANCE: 'bg-orange-100 text-orange-800',
  BANNED: 'bg-red-100 text-red-800',
};

export default function AccountTable({ users, onRefresh }: { users: UserInfo[]; onRefresh: () => void }) {
  const [msg, setMsg] = useState('');

  const handleWithdraw = async (uid: string) => {
    const res = await tryWithdraw(uid, 1000);
    if (res._status) {
      setMsg(`${uid}: ${res.detail} (${res._status})`);
    } else {
      setMsg(`${uid}: 出金成功`);
    }
    setTimeout(() => setMsg(''), 3000);
  };

  const handleRelease = async (uid: string) => {
    try {
      await releaseUser(uid);
      setMsg(`${uid}: 監視解除`);
      onRefresh();
    } catch {
      setMsg(`${uid}: 解除失敗`);
    }
    setTimeout(() => setMsg(''), 3000);
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2 uppercase tracking-wide">アカウント管理</h3>
      {msg && (
        <div className="mb-2 text-xs px-3 py-1.5 rounded bg-blue-50 text-blue-700 border border-blue-200">{msg}</div>
      )}
      <div className="overflow-y-auto max-h-64">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100 text-left text-gray-500 uppercase">
              <th className="py-2 px-2">User ID</th>
              <th className="py-2 px-2">Status</th>
              <th className="py-2 px-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr><td colSpan={3} className="text-center text-gray-400 py-6">ユーザーなし</td></tr>
            )}
            {users.map((u) => (
              <tr key={u.user_id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="py-1.5 px-2 font-mono">{u.user_id}</td>
                <td className="py-1.5 px-2">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATE_BADGE[u.state] || ''}`}>
                    {u.state}
                  </span>
                </td>
                <td className="py-1.5 px-2 text-right space-x-1">
                  <button
                    onClick={() => handleWithdraw(u.user_id)}
                    className="px-2 py-0.5 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs"
                  >
                    出金テスト
                  </button>
                  {u.state === 'UNDER_SURVEILLANCE' && (
                    <button
                      onClick={() => handleRelease(u.user_id)}
                      className="px-2 py-0.5 rounded bg-green-100 hover:bg-green-200 text-green-700 text-xs"
                    >
                      解除
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
