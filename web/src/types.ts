export type EventSource =
  | 'RAZORPAY_TEST_MODE'
  | 'LOCAL_SIMULATION'
  | 'SYNTHETIC_EVALUATION'
  | 'FAKE_PROVIDER';

export interface SanitizedAuditEvent {
  event_id: string;
  source?: EventSource;
  case_id?: string;
  event_type: string;
  actor_type: string;
  before_state?: string;
  after_state?: string;
  safe_reason_code?: string;
  version_info?: string;
  timestamp: string;
  sanitized_metadata: Record<string, any>;
}

export interface BatchRecoveryMetrics {
  total_failures_ingested: number;
  active_cases: number;
  recovered_count: number;
  recovered_gmv_inr: number;
  recovered_gmv_paise: number;
  policy_block_rate: number;
  manual_review_rate: number;
  avg_time_to_recover_seconds: number;
  state_distribution: Record<string, number>;
}

export interface OverviewStats {
  total_failed_events: number;
  active_cases_count: number;
  active_cases_by_state: Record<string, number>;
  total_recovered_cases: number;
  two_evidence_verified_recoveries: number;
  policy_block_rate: number;
  manual_review_rate: number;
  deferred_rate: number;
  no_action_selection_rate: number;
  simulated_notifications_count: number;
  latest_audit_activity: SanitizedAuditEvent[];
  recent_cases: Array<{
    case_id: string;
    source?: EventSource;
    order_id: string;
    amount_paise: number;
    state: string;
    policy_decision?: string;
    ros_score?: number;
    selected_action?: string;
    created_at: string;
  }>;
}

export interface CaseSummary {
  case_id: string;
  source?: EventSource;
  order_id: string;
  amount_paise: number;
  currency: string;
  masked_customer_phone?: string;
  masked_customer_email?: string;
  state: string;
  closure_reason?: string;
  policy_decision?: string;
  ros_score?: number;
  ros_band?: string;
  diagnosis_category?: string;
  selected_action?: string;
  link_status?: string;
  masked_link_id?: string;
  masked_reference_id?: string;
  contact_count: number;
  created_at: string;
  updated_at: string;
}

export interface CaseListResponse {
  items: CaseSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface TimelineEvent {
  step_number: number;
  title: string;
  status: 'success' | 'warning' | 'error' | 'info' | 'pending';
  timestamp: string;
  description: string;
  metadata: Record<string, any>;
}

export interface CaseDetail {
  case_id: string;
  source?: EventSource;
  order_id: string;
  state: string;
  closure_reason?: string;
  contact_count: number;
  created_at: string;
  updated_at: string;
  customer: {
    customer_id: string;
    masked_phone?: string;
    masked_email?: string;
    successful_purchase_count?: number;
    consents: Record<string, string>;
  };
  order: {
    order_id: string;
    amount_paise: number;
    currency: string;
    status: string;
  };
  payment_attempt: {
    payment_id?: string;
    amount_paise?: number;
    currency?: string;
    status?: string;
    method?: string;
    error_code?: string;
    error_description?: string;
    error_source?: string;
    error_step?: string;
    error_reason?: string;
    occurred_at?: string;
  };
  policy_evaluation?: {
    evaluation_id: string;
    policy_version: string;
    decision_type: string;
    reasons: string[];
    evaluated_at: string;
  };
  decision_trace?: {
    trace_id: string;
    policy_decision: string;
    ros_score: number;
    ros_contributions: Record<string, number>;
    diagnosis_category: string;
    diagnosis_confidence: number;
    diagnosis_mode: string;
    diagnosis_fallback_used: boolean;
    action_candidates: string[];
    selected_action: string;
    utility_paise: number;
    created_at: string;
  };
  recovery_action?: {
    action_id: string;
    action_type: string;
    status: string;
    created_at: string;
  };
  payment_link?: {
    link_id: string;
    provider_link_id: string;
    reference_id: string;
    masked_link_id?: string;
    masked_reference_id?: string;
    short_url: string;
    amount_paise: number;
    currency: string;
    status: string;
    expire_by: string;
  };

  notifications: Array<{
    notification_id: string;
    channel: string;
    template_key: string;
    masked_recipient: string;
    link_reference: string;
    status: string;
    simulated_at: string;
  }>;
  budget_reservation?: {
    reservation_id: string;
    amount_paise: number;
    reservation_date: string;
    status: string;
  };
  timeline: TimelineEvent[];
  audit_events: SanitizedAuditEvent[];
}

export interface ConfidenceInterval {
  lower?: number;
  upper?: number;
  confidence_level: number;
  status: string;
}

export interface ArmMetrics {
  strategy: string;
  sample_size: number;
  recovery_count: number;
  recovery_rate: number;
  total_gmv_paise: number;
  recovered_gmv_paise: number;
  total_contacts: number;
  contact_rate: number;
  observed_recovery_gmv_label: string;
}

export interface EvaluationReport {
  evaluation_run_id: string;
  cohort_id: string;
  sample_size: number;
  scenario_seed: number;
  assignment_seed: number;
  generator_version: string;
  policy_version: string;
  ros_version: string;
  estimator_version: string;
  disclaimer: string;
  arm_metrics: Record<string, ArmMetrics>;
  natural_recovery_rate: number;
  estimated_incremental_recovery_conversion: number;
  estimated_incremental_recovery_gmv_paise: number;
  contact_efficiency_paise_per_contact: number;
  incremental_gmv_per_contact_paise: number;
  ci_incremental_conversion: ConfidenceInterval;
  ci_incremental_gmv_paise: ConfidenceInterval;
  ci_incremental_gmv_per_contact_paise: ConfidenceInterval;
  policy_safety_metrics: {
    unsafe_action_rate: number;
    policy_block_rate: number;
    manual_review_rate: number;
    deferred_rate: number;
    no_action_selection_rate: number;
    contact_suppression_rate: number;
  };
  operational_decision_metrics: {
    diagnosis_distribution: Record<string, number>;
    ros_band_distribution: Record<string, number>;
    selected_action_distribution: Record<string, number>;
    avg_decision_latency_ms: number;
  };
}

export interface SettingsData {
  environment: string;
  policy_version: string;
  quiet_hours: Record<string, any>;
  contact_caps: Record<string, any>;
  guardrails: Record<string, any>;
  attribution_reconciliation_window_minutes: number;
  llm_enabled: boolean;
  llm_model: string;
  mapper_version: string;
  ros_version: string;
  estimator_version: string;
}

export interface SimulatorScenario {
  id: string;
  title: string;
  category: string;
  description: string;
  expected_state: string;
  expected_closure_reason?: string;
}

export interface TriggerResponse {
  scenario_id: string;
  title: string;
  status: string;
  case_id?: string;
  order_id?: string;
  final_case_state?: string;
  closure_reason?: string;
  steps_executed: Array<{
    name: string;
    status_code: number;
    response: any;
  }>;
  audit_trail: Array<{
    event_type: string;
    before_state?: string;
    after_state?: string;
    metadata: Record<string, any>;
    timestamp: string;
  }>;
}

export interface ReminderPreview {
  case_id: string;
  eligible: boolean;
  blocking_reasons: string[];
  preview_token?: string;
  expires_at?: string;
  selected_medium: 'sms' | 'email';
  masked_recipient?: string;
  provider_link_id?: string;
  policy_version: string;
}

export interface ReminderSendResponse {
  status: string;
  case_id: string;
  medium: 'sms' | 'email';
  provider_link_id: string;
  provider_notification_id?: string;
  request_id?: string;
  sent_at: string;
}

