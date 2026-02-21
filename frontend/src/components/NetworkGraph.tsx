import { useRef, useCallback, useEffect, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { GraphData } from '../api';

const STATE_COLORS: Record<string, string> = {
  NORMAL: '#22c55e',
  RESTRICTED_WITHDRAWAL: '#eab308',
  UNDER_SURVEILLANCE: '#f97316',
  BANNED: '#dc2626',
};

interface Props {
  data: GraphData | null;
}

export default function NetworkGraph({ data }: Props) {
  const fgRef = useRef<any>(null);
  const [dims, setDims] = useState({ w: 800, h: 400 });
  const containerRef = useRef<HTMLDivElement>(null);
  const [changedNodes, setChangedNodes] = useState<Set<string>>(new Set());
  const prevStates = useRef<Record<string, string>>({});

  useEffect(() => {
    if (!data) return;
    const newChanged = new Set<string>();
    for (const node of data.nodes) {
      const prev = prevStates.current[node.id];
      if (prev && prev !== node.state) {
        newChanged.add(node.id);
      }
      prevStates.current[node.id] = node.state;
    }
    if (newChanged.size > 0) {
      setChangedNodes(newChanged);
      setTimeout(() => setChangedNodes(new Set()), 3000);
    }
  }, [data]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDims({ w: width, h: height });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const label = node.label || node.id;
      const fontSize = 11 / globalScale;
      const r = changedNodes.has(node.id) ? 8 : 6;
      const color = STATE_COLORS[node.state] || '#94a3b8';

      if (changedNodes.has(node.id)) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI);
        ctx.fillStyle = color + '44';
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5 / globalScale;
      ctx.stroke();

      ctx.font = `${fontSize}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#334155';
      ctx.fillText(label, node.x, node.y + r + 2);
    },
    [changedNodes],
  );

  const linkWidth = useCallback((link: any) => {
    return Math.max(1, Math.log10(link.amount || 1));
  }, []);

  const graphData = data ? {
    nodes: data.nodes.map(n => ({ ...n })),
    links: data.links.map(l => ({ ...l })),
  } : { nodes: [], links: [] };

  return (
    <div ref={containerRef} className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden" style={{ height: 400 }}>
      <div className="px-4 pt-3 pb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">資金フローグラフ</h3>
        <div className="flex gap-3 text-xs">
          {Object.entries(STATE_COLORS).map(([k, v]) => (
            <span key={k} className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: v }} />
              {k}
            </span>
          ))}
        </div>
      </div>
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={dims.w}
        height={dims.h - 40}
        nodeCanvasObject={nodeCanvasObject}
        linkWidth={linkWidth}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkColor={() => '#cbd5e1'}
        cooldownTicks={100}
        enableZoomInteraction={true}
        enablePanInteraction={true}
      />
    </div>
  );
}
