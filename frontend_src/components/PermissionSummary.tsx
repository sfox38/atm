import React, { useState, useMemo } from "react";
import type { PermissionTree, NodeState, EntityTree } from "../types";

interface Props {
  permissions: PermissionTree;
  entityTree?: EntityTree | null;
}

const STATE_LABEL: Record<NodeState, string> = {
  GREY: "INHERIT",
  YELLOW: "READ",
  GREEN: "WRITE",
  RED: "DENY",
};

const STATE_CLASS: Record<NodeState, string> = {
  GREY: "state-GREY",
  YELLOW: "state-YELLOW",
  GREEN: "state-GREEN",
  RED: "state-RED",
};

type NodeType = "domain" | "device" | "entity";
type SortCol = "type" | "friendly" | "id" | "state";
type SortDir = "asc" | "desc";

const TYPE_ORDER: Record<NodeType, number> = { domain: 0, device: 1, entity: 2 };
const STATE_ORDER: Record<NodeState, number> = { GREEN: 0, YELLOW: 1, RED: 2, GREY: 3 };

const TYPE_LABEL: Record<NodeType, string> = {
  domain: "Domain",
  device: "Device",
  entity: "Entity",
};

const TYPE_BADGE_STYLE: Record<NodeType, React.CSSProperties> = {
  domain: { background: "rgba(3,169,244,0.12)", color: "var(--primary-color, #03a9f4)" },
  device: { background: "rgba(156,39,176,0.12)", color: "#9c27b0" },
  entity: { background: "rgba(0,0,0,0.07)", color: "var(--secondary-text-color, #727272)" },
};

const BADGE_BASE: React.CSSProperties = {
  display: "inline-block",
  padding: "1px 7px",
  borderRadius: 10,
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  whiteSpace: "nowrap",
};

interface SummaryItem {
  id: string;
  type: NodeType;
  friendlyName: string;
  state: NodeState;
}

function buildLookups(entityTree: EntityTree | null | undefined): {
  entityNames: Map<string, string>;
  deviceNames: Map<string, string>;
} {
  const entityNames = new Map<string, string>();
  const deviceNames = new Map<string, string>();
  if (!entityTree) return { entityNames, deviceNames };
  for (const domain of Object.values(entityTree)) {
    for (const [eid, info] of Object.entries(domain.entity_details)) {
      if (info.friendly_name) entityNames.set(eid, info.friendly_name);
    }
    for (const [did, info] of Object.entries(domain.devices)) {
      deviceNames.set(did, info.name);
    }
  }
  return { entityNames, deviceNames };
}

function SortHeader({
  label,
  col,
  current,
  dir,
  onSort,
}: {
  label: string;
  col: SortCol;
  current: SortCol;
  dir: SortDir;
  onSort: (col: SortCol) => void;
}) {
  const active = current === col;
  const arrow = active ? (dir === "asc" ? " \u25B2" : " \u25BC") : " \u25B4\u25BE";
  return (
    <th
      onClick={() => onSort(col)}
      style={{
        cursor: "pointer",
        userSelect: "none",
        color: active ? "var(--primary-color, #03a9f4)" : "var(--secondary-text-color, #727272)",
        whiteSpace: "nowrap",
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        padding: "6px 8px",
        borderBottom: "2px solid var(--divider-color, #e0e0e0)",
        textAlign: "left",
      }}
    >
      {label}<span style={{ fontSize: 9, opacity: active ? 1 : 0.5 }}>{arrow}</span>
    </th>
  );
}

export function PermissionSummary({ permissions, entityTree }: Props) {
  const [sortCol, setSortCol] = useState<SortCol>("type");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const { entityNames, deviceNames } = useMemo(
    () => buildLookups(entityTree),
    [entityTree],
  );

  const items = useMemo<SummaryItem[]>(() => {
    const result: SummaryItem[] = [];
    for (const [domain, node] of Object.entries(permissions.domains)) {
      if (node.state !== "GREY") {
        result.push({ id: domain, type: "domain", friendlyName: domain, state: node.state });
      }
    }
    for (const [deviceId, node] of Object.entries(permissions.devices)) {
      if (node.state !== "GREY") {
        result.push({
          id: deviceId,
          type: "device",
          friendlyName: deviceNames.get(deviceId) ?? deviceId,
          state: node.state,
        });
      }
    }
    for (const [entityId, node] of Object.entries(permissions.entities)) {
      if (node.state !== "GREY") {
        result.push({
          id: entityId,
          type: "entity",
          friendlyName: entityNames.get(entityId) ?? entityId,
          state: node.state,
        });
      }
    }
    return result;
  }, [permissions, entityNames, deviceNames]);

  const sorted = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortCol === "type") cmp = TYPE_ORDER[a.type] - TYPE_ORDER[b.type];
      else if (sortCol === "friendly") cmp = a.friendlyName.localeCompare(b.friendlyName);
      else if (sortCol === "id") cmp = a.id.localeCompare(b.id);
      else if (sortCol === "state") cmp = STATE_ORDER[a.state] - STATE_ORDER[b.state];
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [items, sortCol, sortDir]);

  function handleSort(col: SortCol) {
    if (col === sortCol) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  }

  if (items.length === 0) {
    return (
      <p style={{ color: "var(--secondary-text-color, #9e9e9e)", fontSize: 13, margin: 0 }}>
        No explicit permissions configured. All access denied by default.
      </p>
    );
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, fontFamily: '"Roboto Mono", monospace' }}>
      <thead>
        <tr>
          <SortHeader label="Type" col="type" current={sortCol} dir={sortDir} onSort={handleSort} />
          <SortHeader label="Name" col="friendly" current={sortCol} dir={sortDir} onSort={handleSort} />
          <SortHeader label="ID" col="id" current={sortCol} dir={sortDir} onSort={handleSort} />
          <SortHeader label="State" col="state" current={sortCol} dir={sortDir} onSort={handleSort} />
        </tr>
      </thead>
      <tbody>
        {sorted.map((item) => (
          <tr key={`${item.type}:${item.id}`} style={{ borderBottom: "1px solid var(--divider-color, #e0e0e0)" }}>
            <td style={{ padding: "5px 8px", whiteSpace: "nowrap" }}>
              <span style={{ ...BADGE_BASE, ...TYPE_BADGE_STYLE[item.type] }}>
                {TYPE_LABEL[item.type]}
              </span>
            </td>
            <td style={{ padding: "5px 8px", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {item.friendlyName !== item.id ? item.friendlyName : <span style={{ color: "var(--secondary-text-color, #9e9e9e)" }}>-</span>}
            </td>
            <td style={{ padding: "5px 8px", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--secondary-text-color, #9e9e9e)" }}>
              {item.id}
            </td>
            <td style={{ padding: "5px 8px", whiteSpace: "nowrap" }}>
              <span className={STATE_CLASS[item.state]}>{STATE_LABEL[item.state]}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
