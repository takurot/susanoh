import { useRef, useCallback, useEffect, useState } from 'react';
import ForceGraph2D, {
  type ForceGraphMethods,
  type NodeObject,
} from 'react-force-graph-2d';
import type { GraphData, GraphNode } from '../api';

const STATE_COLORS: Record<string, string> = {
  NORMAL: '#22c55e',
  RESTRICTED_WITHDRAWAL: '#eab308',
  UNDER_SURVEILLANCE: '#f97316',
  BANNED: '#dc2626',
};

interface Props {
  data: GraphData | null;
}

type GraphNodeObject = NodeObject<GraphNode>;
interface GraphLinkObject {
  source: string | number | GraphNodeObject;
  target: string | number | GraphNodeObject;
  amount: number;
  count: number;
}

interface StableGraphData {
  nodes: GraphNodeObject[];
  links: GraphLinkObject[];
}

function nodeIdOf(node: GraphNodeObject | string | number | undefined): string {
  if (node && typeof node === 'object') {
    return String(node.id ?? '');
  }
  return String(node ?? '');
}

function linkKeyOf(source: GraphNodeObject | string | number | undefined, target: GraphNodeObject | string | number | undefined): string {
  return `${nodeIdOf(source)}→${nodeIdOf(target)}`;
}

function linkKey(link: Pick<GraphLinkObject, 'source' | 'target'>): string {
  return linkKeyOf(link.source, link.target);
}

export default function NetworkGraph({ data }: Props) {
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLinkObject> | undefined>(undefined);
  const [dims, setDims] = useState({ w: 800, h: 400 });
  const containerRef = useRef<HTMLDivElement>(null);
  const prevStates = useRef<Record<string, string>>({});
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});
  const [stableData, setStableData] = useState<StableGraphData>({ nodes: [], links: [] });

  useEffect(() => {
    const nodeSet = new Set(stableData.nodes);
    const detachedLinks = stableData.links.filter((link) => {
      const sourceDetached = typeof link.source === 'object' && !nodeSet.has(link.source);
      const targetDetached = typeof link.target === 'object' && !nodeSet.has(link.target);
      return sourceDetached || targetDetached;
    }).length;

    if (import.meta.env.DEV) {
      (window as Window & {
        __susanohGraphDebug?: { detachedLinks: number; nodes: number; links: number };
      }).__susanohGraphDebug = {
        detachedLinks,
        nodes: stableData.nodes.length,
        links: stableData.links.length,
      };
    }
  }, [stableData]);

  useEffect(() => {
    if (!data) return;

    let stateChanged = false;
    for (const node of data.nodes) {
      const prev = prevStates.current[node.id];
      if (prev && prev !== node.state) {
        stateChanged = true;
      }
      prevStates.current[node.id] = node.state;
    }

    let shouldReheat = false;
    setStableData((prev) => {
      for (const n of prev.nodes) {
        const id = nodeIdOf(n);
        if (id && n.x != null && n.y != null) {
          positionsRef.current[id] = { x: n.x, y: n.y };
        }
      }

      const prevNodeMap = new Map<string, GraphNodeObject>(prev.nodes.map((n) => [nodeIdOf(n), n]));
      const prevLinkMap = new Map<string, GraphLinkObject>(prev.links.map((l) => [linkKey(l), l]));

      const nextNodes: GraphNodeObject[] = data.nodes.map((incoming) => {
        const existing = prevNodeMap.get(incoming.id);
        if (existing) {
          existing.state = incoming.state;
          existing.label = incoming.label;
          return existing;
        }
        const pos = positionsRef.current[incoming.id];
        return pos ? { ...incoming, x: pos.x, y: pos.y } : { ...incoming };
      });
      const nextNodeMap = new Map<string, GraphNodeObject>(nextNodes.map((n) => [nodeIdOf(n), n]));

      const nextLinks: GraphLinkObject[] = data.links
        .filter((incoming) => nextNodeMap.has(String(incoming.source)) && nextNodeMap.has(String(incoming.target)))
        .map((incoming) => {
          const key = linkKeyOf(incoming.source, incoming.target);
          const existing = prevLinkMap.get(key);
          const sourceNode = nextNodeMap.get(String(incoming.source));
          const targetNode = nextNodeMap.get(String(incoming.target));
          if (!sourceNode || !targetNode) {
            return {
              source: String(incoming.source),
              target: String(incoming.target),
              amount: incoming.amount,
              count: incoming.count,
            };
          }
          if (existing) {
            existing.source = sourceNode;
            existing.target = targetNode;
            existing.amount = incoming.amount;
            existing.count = incoming.count;
            return existing;
          }
          return {
            source: sourceNode,
            target: targetNode,
            amount: incoming.amount,
            count: incoming.count,
          };
        });

      const prevNodeIds = new Set(prev.nodes.map((n) => nodeIdOf(n)));
      const nextNodeIds = new Set(nextNodes.map((n) => nodeIdOf(n)));
      const nodeTopologyChanged =
        prevNodeIds.size !== nextNodeIds.size
        || [...nextNodeIds].some((id) => !prevNodeIds.has(id));

      const prevLinkKeys = new Set(prev.links.map((l) => linkKey(l)));
      const nextLinkKeys = new Set(data.links.map((l) => linkKeyOf(l.source, l.target)));
      const linkTopologyChanged =
        prevLinkKeys.size !== nextLinkKeys.size
        || [...nextLinkKeys].some((k) => !prevLinkKeys.has(k));

      shouldReheat = nodeTopologyChanged || linkTopologyChanged || stateChanged;
      return { nodes: nextNodes, links: nextLinks };
    });

    if (shouldReheat && fgRef.current) {
      window.setTimeout(() => fgRef.current?.d3ReheatSimulation(), 100);
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
    (node: GraphNodeObject, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const label = node.label || node.id;
      const fontSize = 11 / globalScale;
      const r = 6;
      const color = STATE_COLORS[node.state || ''] || '#94a3b8';

      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5 / globalScale;
      ctx.stroke();

      ctx.font = `${fontSize}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#334155';
      ctx.fillText(String(label ?? ''), (node.x ?? 0), (node.y ?? 0) + r + 2);
    },
    [],
  );

  const linkWidth = useCallback((link: GraphLinkObject) => {
    return Math.max(1, Math.log10(link.amount || 1));
  }, []);

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
      <ForceGraph2D<GraphNode, GraphLinkObject>
        ref={fgRef}
        graphData={stableData}
        width={dims.w}
        height={dims.h - 40}
        nodeCanvasObject={nodeCanvasObject}
        linkWidth={linkWidth}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkColor={() => '#cbd5e1'}
        cooldownTicks={50}
        warmupTicks={0}
        enableZoomInteraction={true}
        enablePanInteraction={true}
      />
    </div>
  );
}
