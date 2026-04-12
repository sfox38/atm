import React from "react";
import type { NodeState } from "../types";

interface Props {
  value: NodeState;
  onChange: (state: NodeState) => void;
  disabled?: boolean;
}

const BUTTONS: { state: NodeState; label: string; title: string }[] = [
  { state: "GREY", label: "N", title: "No explicit grant (inherits from parent)" },
  { state: "YELLOW", label: "R", title: "Read-only" },
  { state: "GREEN", label: "W", title: "Read and write" },
  { state: "RED", label: "D", title: "Deny (overrides all children)" },
];

export function PermissionSelector({ value, onChange, disabled }: Props) {
  return (
    <div className="perm-selector" aria-label="Permission">
      {BUTTONS.map(({ state, label, title }) => (
        <button
          key={state}
          title={title}
          className={`perm-btn${value === state ? ` active-${state}` : ""}`}
          onClick={() => !disabled && onChange(state)}
          disabled={disabled}
          aria-pressed={value === state}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
