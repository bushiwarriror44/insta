export interface Health {
  ok: boolean;
  version: string;
  auth_required: boolean;
}

export type AuthRole = "owner" | "operator";

export interface AuthMeOut {
  role: AuthRole | null;
  label: string | null;
}

export interface PanelGateOut {
  allowed: boolean;
  entry_path: string | null;
}

export interface PanelSettingsOut {
  entry_path: string;
  master_password_set: boolean;
}

export interface LlmGatewayActivityOut {
  at: string;
  channel: "llm" | "mcp";
  method: string;
  path: string;
  client_ip: string;
  user_agent: string;
  status: number;
  detail?: string;
}

export interface LlmGatewayCredentialsOut {
  base_url: string;
  api_key: string;
  mcp_url: string;
  mcp_json: string;
  model: string;
  upstream_ok: boolean;
  enabled: boolean;
  recent: LlmGatewayActivityOut[];
}

export interface AdminNotesOut {
  content: string;
  updated_at: string | null;
}

export interface PanelOperatorOut {
  id: number;
  label: string;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  active: boolean;
}

export interface PanelOperatorCreatedOut extends PanelOperatorOut {
  password: string;
}

export interface ProxyOut {
  id: number;
  label: string;
  url: string;
  country: string | null;
  timezone: string | null;
  is_healthy: boolean;
  last_known_ip: string | null;
  last_geo_country: string | null;
  last_checked_at: string | null;
  notes: string | null;
  accounts_count: number;
  instagram_reachable?: boolean | null;
  geo_mismatch_warning?: boolean;
  check_detail?: string | null;
}

export type FloppydataProxyType = "residential" | "mobile" | "datacenter";
export type FloppydataProtocol = "http" | "https" | "socks5";

export interface FloppydataStatusOut {
  configured: boolean;
  key_from_env: boolean;
  balance_gb?: number | null;
  balance_bytes?: number | null;
  expiring_gb?: number | null;
  expiring_at?: string | null;
  error?: string | null;
}

export interface FloppydataGenerateIn {
  type: FloppydataProxyType;
  country: string;
  city?: string | null;
  state?: string | null;
  protocol: FloppydataProtocol;
  rotation: number;
  udp?: boolean;
  subuser_id?: number | null;
  count: number;
}

export interface FloppydataConnectionOut {
  connection_string: string;
  protocol: string;
  host: string;
  port: number | null;
  username: string;
  password: string;
}

export interface FloppydataGenerateOut {
  items: FloppydataConnectionOut[];
}

export interface FloppydataImportItemIn {
  label?: string | null;
  url: string;
  country?: string | null;
}

export interface FloppydataImportIn {
  items: FloppydataImportItemIn[];
  run_health_check?: boolean;
}

export interface FloppydataLocationCountry {
  code?: string;
  countryCode?: string;
  name?: string;
  countryName?: string;
  cities?: string[];
  states?: string[];
}

export interface ProxyIn {
  label: string;
  url: string;
  country?: string | null;
  timezone?: string | null;
  notes?: string | null;
  skip_health_check?: boolean;
}

export interface ProxyUpdate {
  url: string;
  country?: string | null;
  timezone?: string | null;
  notes?: string | null;
  skip_health_check?: boolean;
}

export type AccountStatus =
  | "active"
  | "paused"
  | "challenge"
  | "blocked"
  | "cooldown";

export type CaptionProfile =
  | "nature"
  | "lifestyle"
  | "fitness"
  | "food"
  | "travel";

export const CAPTION_PROFILE_OPTIONS: CaptionProfile[] = [
  "nature",
  "lifestyle",
  "fitness",
  "food",
  "travel",
];

export type LoginSurface = "mobile" | "desktop";

export interface AccountOut {
  id: number;
  username: string;
  platform?: "instagram" | "youtube" | "tiktok";
  login_identifier?: string | null;
  status: AccountStatus | string;
  proxy_id: number | null;
  proxy_label: string | null;
  proxy_country: string | null;
  proxy_geo_country: string | null;
  proxy_is_healthy: boolean | null;
  proxy_last_ip: string | null;
  timezone: string;
  daily_post_cap: number;
  min_gap_hours: number;
  active_hour_start: number;
  active_hour_end: number;
  last_publish_at: string | null;
  last_idle_warmup_at: string | null;
  last_session_rotation_at: string | null;
  cooldown_until: string | null;
  caption_profile: string | null;
  has_totp: boolean;
  has_session_id: boolean;
  login_surface?: LoginSurface | null;
  session_file_exists: boolean;
  session_file_updated_at: string | null;
  session_source: "database" | "session_file" | "playwright" | "none";
  posts_today: number;
  failures_today: number;
  notes?: string | null;
  brief?: string | null;
  hold_for_review?: boolean;
  daily_spend_cap_usd?: number;
}

export interface AccountNotesUpdate {
  notes?: string | null;
}

export interface AccountTotpOut {
  totp_seed: string;
  code: string;
  seconds_remaining: number;
}

export interface AccountIn {
  username: string;
  platform?: "instagram" | "youtube" | "tiktok";
  password: string;
  proxy_label: string;
  timezone?: string;
  daily_post_cap?: number;
  min_gap_hours?: number;
  active_hour_start?: number;
  active_hour_end?: number;
  caption_profile?: string | null;
  totp_seed?: string | null;
  session_id?: string | null;
  login_identifier?: string | null;
  email?: string | null;
  email_password?: string | null;
  imap_host?: string | null;
  backup_codes?: string | null;
  login_surface?: LoginSurface | null;
  account_line?: string | null;
  notes?: string | null;
}

export interface AccountProxyUpdate {
  proxy_label: string;
}

export interface AccountSessionUpdate {
  session_id: string;
}

export interface AccountSessionOut {
  session_id: string;
  source: "database" | "session_file";
  session_file_exists: boolean;
}

export interface CookiesImportOut {
  format: "dolphin" | "playwright_state";
  session_id: string;
  session_id_imported: boolean;
  playwright_state_saved: boolean;
  session_file_cleared: boolean;
}

export interface DeviceFingerprintImportOut {
  username: string;
  saved: boolean;
}

export interface ProxyHealthStepOut {
  ok: boolean;
  ip?: string | null;
  geo_country?: string | null;
  instagram_reachable: boolean;
  instagram_login_reachable?: boolean;
  geo_mismatch: boolean;
  error?: string | null;
}

export interface SessionStorageStepOut {
  has_session_id: boolean;
  session_file_exists: boolean;
  device_file_exists: boolean;
  session_source: "database" | "session_file" | "playwright" | "none";
}

export interface InstagramAuthStepOut {
  ok: boolean;
  method: "sessionid" | "session_file" | "playwright" | "none";
  ig_username?: string | null;
  error?: string | null;
  error_code?: "session_missing" | "session_expired" | "challenge_required" | null;
  challenge: boolean;
}

export interface DiagnosticLogLine {
  ts: string;
  level: "info" | "warn" | "error";
  step: string;
  message: string;
}

export interface DiagnosticRunOut {
  id: number;
  kind: "connection_test" | "publish_job" | "first_login" | "mint_mobile_session" | "browser_session";
  account_id: number;
  account_username: string | null;
  job_id: number | null;
  status: "running" | "ok" | "warn" | "fail";
  summary: string | null;
  logs: DiagnosticLogLine[];
  created_at: string;
  finished_at: string | null;
}

export interface AccountConnectionTestOut {
  username: string;
  proxy_assigned: boolean;
  proxy_label?: string | null;
  proxy_health: ProxyHealthStepOut;
  session_storage: SessionStorageStepOut;
  instagram_auth: InstagramAuthStepOut;
  overall_ok: boolean;
  checked_at: string;
  run_id: number;
  logs: DiagnosticLogLine[];
}

export interface FirstLoginOut {
  run_id: number;
  ok: boolean;
  challenge: boolean;
  browser_tab_hint?: boolean;
  session_imported: boolean;
  connection_test?: AccountConnectionTestOut | null;
  error?: string | null;
  login_debug_available: boolean;
  logs: DiagnosticLogLine[];
}

export interface MintMobileSessionOut {
  run_id: number;
  ok: boolean;
  challenge: boolean;
  session_id?: string | null;
  error?: string | null;
  logs: DiagnosticLogLine[];
}

export type BrowserSessionStatus =
  | "starting"
  | "running"
  | "awaiting_code"
  | "saved"
  | "error"
  | "stopped";

export interface BrowserSessionOut {
  username: string;
  status: BrowserSessionStatus;
  awaiting_code: boolean;
  vnc_path?: string | null;
  page_url?: string | null;
  error?: string | null;
  login_surface?: LoginSurface | null;
  warning?: string | null;
  proxy_label?: string | null;
  proxy_ip?: string | null;
  proxy_geo_country?: string | null;
  proxy_country?: string | null;
  proxy_timezone?: string | null;
  proxy_instagram_reachable?: boolean | null;
  proxy_instagram_login_reachable?: boolean | null;
  proxy_instagram_login_http_status?: number | null;
  account_username?: string | null;
  account_login?: string | null;
  account_password?: string | null;
  account_notes?: string | null;
  logs?: DiagnosticLogLine[];
}

export interface BrowserSaveOut extends BrowserSessionOut {
  session_imported: boolean;
  session_id_saved: boolean;
  overall_ok: boolean;
  connection_test?: AccountConnectionTestOut | null;
  logs?: DiagnosticLogLine[];
}

export interface VideoOut {
  filename: string;
  size_bytes: number;
  modified_at: string;
  media_type: "image" | "video";
  duration_sec?: number | null;
}

export interface UploadOut {
  filename: string;
  size_bytes: number;
  media_type: "image" | "video";
  duration_sec?: number | null;
}

export type PostType = "reel" | "feed_photo" | "feed_video" | "youtube_short" | "tiktok";

export type JobStatus =
  | "awaiting_review"
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "dead"
  | "cancelled";

export interface JobOut {
  id: number;
  account_id: number;
  account_username: string | null;
  source_video_path: string;
  post_type: PostType | string;
  caption_template: string | null;
  title?: string;
  description?: string;
  tags?: string;
  scheduled_for: string;
  status: JobStatus | string;
  attempts: number;
  last_error: string | null;
  next_attempt_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
}

export interface EnqueueIn {
  username: string;
  account_id?: number | null;
  media_filename?: string;
  video_filename?: string;
  post_type?: PostType;
  caption_template?: string | null;
  title?: string | null;
  description?: string | null;
  tags?: string | null;
  privacy?: string | null;
  when?: string | null;
}

export interface PublicationOut {
  id: number;
  job_id: number;
  account_id: number;
  account_username: string | null;
  post_type: PostType | string | null;
  media_id: string | null;
  media_code: string | null;
  final_media_path: string | null;
  final_caption: string | null;
  success: boolean;
  error: string | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  play_count: number | null;
  save_count: number | null;
  share_count: number | null;
  last_stats_at: string | null;
  created_at: string;
}

export type EventLevel = "info" | "warn" | "error" | "critical";

export interface EventOut {
  id: number;
  account_id: number | null;
  account_username: string | null;
  level: EventLevel | string;
  kind: string;
  message: string;
  created_at: string;
}

export interface DailyStatRow {
  username: string;
  posts_count: number;
  failures_count: number;
}

export interface DashboardSummary {
  accounts_total: number;
  accounts_active: number;
  accounts_blocked: number;
  proxies_healthy: number;
  proxies_total: number;
  jobs_queued: number;
  jobs_running: number;
  jobs_done_today: number;
  jobs_dead_total: number;
  jobs_awaiting_review?: number;
  jobs_failed_24h?: number;
  open_questions?: number;
  questions_account_id?: number | null;
  risk_signals_24h: number;
  quarantined_accounts: number;
  daily_stats: DailyStatRow[];
  recent_events: EventOut[];
}

export interface WorkerProcessOut {
  running: boolean;
  ours: boolean;
  pid: number | null;
  seen_at: string | null;
  note: string;
}

export interface LogTailOut {
  name: string;
  available: boolean;
  reason: string;
  lines: string[];
}

export interface GpuLogsOut {
  docker: LogTailOut[];
  gpu: LogTailOut;
}

export interface GpuOut {
  configured: boolean;
  status: string | null;
  billing: boolean;
  allocating_count: number;
  creating_count: number;
  running_count: number;
  stopping_count: number;
  chat_ok: boolean;
  wan_ok: boolean | null;
  detail: string;
  idle_stop_minutes?: number;
  deploy_started_at?: string | null;
  connect_phase?: "idle" | "pull" | "boot" | "gateway" | "ready";
  connect_label?: string;
  connect_detail?: string;
  connect_ratio?: number;
}

export interface RenderBackendOut {
  name: string;
  healthy: boolean;
  licence: string;
  experimental: boolean;
  detail: string;
  supports_i2v?: boolean;
  supports_v2v?: boolean;
  supports_slideshow?: boolean;
}

export interface MediaAssetOut {
  id: number;
  filename: string;
  kind: string;
  source: string;
  label: string;
  prompt: string | null;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  created_at: string;
}

export interface RuntimeOut {
  reachable: boolean;
  base_url: string;
  models: string[];
  loaded: Array<{ name: string; context: number; size_bytes: number }>;
  detail: string | null;
  model: string;
  context: number | null;
}

export interface BackupOut {
  name: string;
  bytes: number;
  taken_at: string;
}

