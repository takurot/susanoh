import { useRef, useCallback, useEffect, useState } from 'react';
import ForceGraph2D, {
  type ForceGraphMethods,
  type NodeObject,
} from 'react-force-graph-2d';
import type { GraphData, GraphNode } from '../api';
import {
  isSuspiciousLink,
  shouldGlowBanned,
  shouldHighlightTransition,
} from './graphCinematic';

const STATE_COLORS: Record<string, string> = {
  NORMAL: '#22c55e',
  RESTRICTED_WITHDRAWAL: '#eab308',
  UNDER_SURVEILLANCE: '#f97316',
  BANNED: '#dc2626',
};
const NODE_HIGHLIGHT_MS = 2200;
const BANNED_GLOW_MS = 3000;
const EDGE_BOOST_MS = 2200;

interface Props {
  data: GraphData | null;
  focusTargetId?: string | null;
  focusRequestId?: number;
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

function isEffectActive(effectMap: Record<string, number>, now: number): boolean {
  return Object.values(effectMap).some((expiresAt) => expiresAt > now);
}

function pruneExpiredEffects(effectMap: Record<string, number>, now: number): void {
  for (const [id, expiresAt] of Object.entries(effectMap)) {
    if (expiresAt <= now) {
      delete effectMap[id];
    }
  }
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

export default function NetworkGraph({ data, focusTargetId = null, focusRequestId = 0 }: Props) {
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLinkObject> | undefined>(undefined);
  const [dims, setDims] = useState({ w: 800, h: 400 });
  const containerRef = useRef<HTMLDivElement>(null);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const prevStates = useRef<Record<string, string>>({});
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});
  const nodeHighlightUntilRef = useRef<Record<string, number>>({});
  const nodeBannedGlowUntilRef = useRef<Record<string, number>>({});
  const linkBoostUntilRef = useRef<Record<string, number>>({});
  const animationFrameRef = useRef<number | null>(null);
  const effectFrameRunnerRef = useRef<() => void>(() => {});
  const focusResetTimeoutRef = useRef<number | null>(null);
  const lastFocusRequestRef = useRef(0);
  const [stableData, setStableData] = useState<StableGraphData>({ nodes: [], links: [] });
  const stableDataRef = useRef<StableGraphData>({ nodes: [], links: [] });
  const pendingReheatRef = useRef(false);

  const redrawGraph = useCallback(() => {
    const fg = fgRef.current as
      | (ForceGraphMethods<GraphNode, GraphLinkObject> & { refresh?: () => void })
      | undefined;
    fg?.refresh?.();
  }, []);

  const hasAnyActiveEffects = useCallback(() => {
    const now = Date.now();
    return (
      isEffectActive(nodeHighlightUntilRef.current, now)
      || isEffectActive(nodeBannedGlowUntilRef.current, now)
      || isEffectActive(linkBoostUntilRef.current, now)
    );
  }, []);

  const stopEffectLoop = useCallback(() => {
    if (animationFrameRef.current != null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  }, []);

  const ensureEffectLoop = useCallback(() => {
    if (prefersReducedMotion) return;
    if (animationFrameRef.current != null) return;
    if (!hasAnyActiveEffects()) return;
    animationFrameRef.current = window.requestAnimationFrame(() => {
      effectFrameRunnerRef.current();
    });
  }, [hasAnyActiveEffects, prefersReducedMotion]);

  useEffect(() => {
    effectFrameRunnerRef.current = () => {
      const now = Date.now();
      pruneExpiredEffects(nodeHighlightUntilRef.current, now);
      pruneExpiredEffects(nodeBannedGlowUntilRef.current, now);
      pruneExpiredEffects(linkBoostUntilRef.current, now);
      redrawGraph();

      if (hasAnyActiveEffects()) {
        animationFrameRef.current = window.requestAnimationFrame(() => {
          effectFrameRunnerRef.current();
        });
      } else {
        animationFrameRef.current = null;
      }
    };
  }, [hasAnyActiveEffects, redrawGraph]);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setPrefersReducedMotion(mediaQuery.matches);
    onChange();
    mediaQuery.addEventListener('change', onChange);
    return () => mediaQuery.removeEventListener('change', onChange);
  }, []);

  useEffect(() => {
    if (!prefersReducedMotion) return;
    nodeHighlightUntilRef.current = {};
    nodeBannedGlowUntilRef.current = {};
    linkBoostUntilRef.current = {};
    stopEffectLoop();
  }, [prefersReducedMotion, stopEffectLoop]);

  useEffect(() => {
    return () => {
      stopEffectLoop();
      if (focusResetTimeoutRef.current != null) {
        window.clearTimeout(focusResetTimeoutRef.current);
        focusResetTimeoutRef.current = null;
      }
    };
  }, [stopEffectLoop]);

  useEffect(() => {
    stableDataRef.current = stableData;

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

    if (pendingReheatRef.current && fgRef.current) {
      pendingReheatRef.current = false;
      window.setTimeout(() => fgRef.current?.d3ReheatSimulation(), 100);
    }
  }, [stableData]);

  useEffect(() => {
    if (!data) return;

    const now = Date.now();
    let stateChanged = false;
    for (const node of data.nodes) {
      const prev = prevStates.current[node.id];
      if (prev && prev !== node.state) {
        stateChanged = true;
      }
      if (!prefersReducedMotion && shouldHighlightTransition(prev, node.state)) {
        nodeHighlightUntilRef.current[node.id] = now + NODE_HIGHLIGHT_MS;
      }
      if (!prefersReducedMotion && shouldGlowBanned(prev, node.state)) {
        nodeBannedGlowUntilRef.current[node.id] = now + BANNED_GLOW_MS;
      }
      prevStates.current[node.id] = node.state;
    }

    const prev = stableDataRef.current;
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
        if (!prefersReducedMotion && isSuspiciousLink(incoming)) {
          linkBoostUntilRef.current[key] = now + EDGE_BOOST_MS;
        }
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

    pendingReheatRef.current = nodeTopologyChanged || linkTopologyChanged || stateChanged;
    setStableData({ nodes: nextNodes, links: nextLinks });
    ensureEffectLoop();
  }, [data, ensureEffectLoop, prefersReducedMotion]);

  useEffect(() => {
    if (!focusTargetId || focusRequestId <= 0) return;
    if (focusRequestId === lastFocusRequestRef.current) return;

    const targetNode = stableData.nodes.find((node) => nodeIdOf(node) == focusTargetId);
    if (!targetNode || targetNode.x == null || targetNode.y == null || !fgRef.current) return;

    if (focusResetTimeoutRef.current != null) {
      window.clearTimeout(focusResetTimeoutRef.current);
      focusResetTimeoutRef.current = null;
    }

    const centerDuration = prefersReducedMotion ? 220 : 700;
    const focusZoom = prefersReducedMotion ? 1.65 : 2.15;
    fgRef.current.centerAt(targetNode.x, targetNode.y, centerDuration);
    fgRef.current.zoom(focusZoom, centerDuration);

    if (!prefersReducedMotion) {
      focusResetTimeoutRef.current = window.setTimeout(() => {
        fgRef.current?.zoom(1.35, 900);
        focusResetTimeoutRef.current = null;
      }, 900);
    }

    lastFocusRequestRef.current = focusRequestId;
  }, [focusRequestId, focusTargetId, prefersReducedMotion, stableData.nodes]);

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
      const nodeId = nodeIdOf(node);
      const now = Date.now();
      const label = node.label || node.id;
      const fontSize = 11 / globalScale;
      const r = 6;
      const color = STATE_COLORS[node.state || ''] || '#94a3b8';
      const x = node.x ?? 0;
      const y = node.y ?? 0;

      const highlightUntil = nodeHighlightUntilRef.current[nodeId] ?? 0;
      if (highlightUntil > now) {
        const progress = (highlightUntil - now) / NODE_HIGHLIGHT_MS;
        const pulse = prefersReducedMotion ? 1 : 0.65 + 0.35 * Math.sin(now / 120);
        const radius = r + 4 + (1 - progress) * 6;
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(59, 130, 246, ${0.5 * progress * pulse})`;
        ctx.lineWidth = 2.6 / globalScale;
        ctx.stroke();
        ctx.restore();
      }

      const bannedGlowUntil = nodeBannedGlowUntilRef.current[nodeId] ?? 0;
      if (bannedGlowUntil > now) {
        const progress = (bannedGlowUntil - now) / BANNED_GLOW_MS;
        const pulse = prefersReducedMotion ? 1 : 0.75 + 0.25 * Math.sin(now / 110);
        const alpha = 0.3 + 0.4 * progress * pulse;
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, r + 5, 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(220, 38, 38, ${alpha})`;
        ctx.lineWidth = 3.8 / globalScale;
        ctx.shadowColor = `rgba(220, 38, 38, ${alpha})`;
        ctx.shadowBlur = 14 / globalScale;
        ctx.stroke();
        ctx.restore();
      }

      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5 / globalScale;
      ctx.stroke();

      ctx.font = `${fontSize}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#334155';
      ctx.fillText(String(label ?? ''), x, y + r + 2);
    },
    [prefersReducedMotion],
  );

  const linkWidth = useCallback((link: GraphLinkObject) => {
    const base = Math.max(1, Math.log10(link.amount || 1));
    const boostUntil = linkBoostUntilRef.current[linkKey(link)] ?? 0;
    if (boostUntil > Date.now()) {
      return base * 2.2;
    }
    return base;
  }, []);

  const linkColor = useCallback((link: GraphLinkObject) => {
    const boostUntil = linkBoostUntilRef.current[linkKey(link)] ?? 0;
    if (boostUntil > Date.now()) {
      return '#fb7185';
    }
    return '#cbd5e1';
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
        linkColor={linkColor}
        cooldownTicks={50}
        warmupTicks={0}
        enableZoomInteraction={true}
        enablePanInteraction={true}
      />
    </div>
  );
}
