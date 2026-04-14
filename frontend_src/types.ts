export type NodeState = "GREY" | "YELLOW" | "GREEN" | "RED";
export type Permission = "WRITE" | "READ" | "DENY" | "NO_ACCESS" | "NOT_FOUND";
export type Outcome = "allowed" | "denied" | "not_found" | "rate_limited" | "not_implemented";

export interface PermissionNode {
  state: NodeState;
  hint: string | null;
}

export interface PermissionTree {
  domains: Record<string, PermissionNode>;
  devices: Record<string, PermissionNode>;
  entities: Record<string, PermissionNode>;
}

export interface TokenRecord {
  id: string;
  name: string;
  token_hash: string;
  created_at: string;
  created_by: string;
  expires_at: string | null;
  revoked: boolean;
  last_used_at: string | null;
  updated_at: string | null;
  pass_through: boolean;
  rate_limit_requests: number;
  rate_limit_burst: number;
  allow_automation_write: boolean;
  allow_script_write: boolean;
  allow_config_read: boolean;
  allow_template_render: boolean;
  allow_restart: boolean;
  allow_service_response: boolean;
  allow_broadcast: boolean;
  permissions: PermissionTree;
}

export interface TokenCreateResponse extends TokenRecord {
  token: string;
}

export interface ArchivedTokenRecord {
  id: string;
  name: string;
  token_hash: string;
  created_at: string;
  created_by: string;
  revoked_at: string;
  revoked: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  pass_through: boolean;
}

export interface GlobalSettings {
  kill_switch: boolean;
  disable_all_logging: boolean;
  log_allowed: boolean;
  log_denied: boolean;
  log_rate_limited: boolean;
  log_entity_names: boolean;
  log_client_ip: boolean;
  notify_on_rate_limit: boolean;
  audit_flush_interval: number;
  audit_log_maxlen: number;
}

export interface AuditEntry {
  request_id: string;
  timestamp: string;
  token_id: string;
  token_name: string;
  method: string;
  resource: string;
  outcome: Outcome;
  client_ip: string;
  pass_through: boolean;
}

export interface EntityInfo {
  entity_id: string;
  friendly_name: string | null;
  device_id: string | null;
  area_id: string | null;
  area_name: string | null;
}

export interface DeviceInfo {
  device_id: string;
  name: string;
  area_id: string | null;
  area_name: string | null;
  entities: string[];
}

export interface DomainTree {
  devices: Record<string, DeviceInfo>;
  deviceless_entities: string[];
  entity_details: Record<string, EntityInfo>;
}

export type EntityTree = Record<string, DomainTree>;

export interface ResolutionStep {
  level: string;
  state: string;
}

export interface ResolveResult {
  entity_id: string;
  resolution_path: ResolutionStep[];
  effective: Permission;
  effective_hint: string | null;
}

export interface TokenStats {
  token_id: string;
  token_name: string;
  request_count: number;
  denied_count: number;
  rate_limit_hits: number;
  last_used_at: string | null;
  status: string;
}

export interface ScopeResult {
  token_id: string;
  token_name: string;
  readable: string[];
  writable: string[];
  capability_flags: {
    allow_config_read: boolean;
    allow_automation_write: boolean;
    allow_script_write: boolean;
    allow_template_render: boolean;
    allow_restart: boolean;
  };
}

export interface CreateTokenBody {
  name: string;
  expires_at?: string;
  pass_through?: boolean;
  confirm_pass_through?: boolean;
  rate_limit_requests?: number;
  rate_limit_burst?: number;
}

export interface PatchTokenBody {
  pass_through?: boolean;
  confirm_pass_through?: boolean;
  rate_limit_requests?: number;
  rate_limit_burst?: number;
  allow_automation_write?: boolean;
  allow_script_write?: boolean;
  allow_config_read?: boolean;
  allow_template_render?: boolean;
  allow_restart?: boolean;
  allow_service_response?: boolean;
  allow_broadcast?: boolean;
}

export interface PermissionPatchBody {
  state: NodeState;
  hint?: string | null;
}

export interface AuditQueryParams {
  limit?: number;
  offset?: number;
  token_id?: string;
  outcome?: string;
  ip?: string;
}

declare global {
  namespace React.JSX {
    interface IntrinsicElements {
      "ha-card": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        header?: string;
        outlined?: boolean;
      };
      "ha-switch": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        checked?: boolean;
        disabled?: boolean;
      };
      "ha-icon": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        icon?: string;
      };
      "ha-icon-button": React.DetailedHTMLProps<React.ButtonHTMLAttributes<HTMLElement>, HTMLElement> & {
        label?: string;
        disabled?: boolean;
      };
      "ha-circular-progress": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        active?: boolean;
        size?: string;
      };
    }
  }
}
