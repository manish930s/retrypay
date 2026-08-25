import {
  BatchRecoveryMetrics,
  CaseDetail,
  CaseListResponse,
  EvaluationReport,
  OverviewStats,
  SettingsData,
  SimulatorScenario,
  TriggerResponse,
} from './types';

export function resolveApiBase(explicitBase?: string): string {
  const configuredBase = explicitBase ?? import.meta.env.VITE_API_BASE_URL;
  const normalized = configuredBase?.trim();
  if (!normalized) {
    return '/api/v1';
  }
  return normalized.replace(/\/+$/, '');
}

const API_BASE = resolveApiBase();

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!resp.ok) {
    const errorBody = await resp.text();
    throw new Error(`API Error ${resp.status}: ${errorBody || resp.statusText}`);
  }

  return resp.json();
}

export const api = {
  getOverview: (): Promise<OverviewStats> => fetchJSON<OverviewStats>('/dashboard/overview'),

  getBatchMetrics: (): Promise<BatchRecoveryMetrics> =>
    fetchJSON<BatchRecoveryMetrics>('/metrics/batch'),

  getCases: (params?: {
    source?: string;
    state?: string;
    policy_decision?: string;
    diagnosis_category?: string;
    ros_band?: string;
    link_status?: string;
    limit?: number;
    offset?: number;
  }): Promise<CaseListResponse> => {
    const query = new URLSearchParams();
    if (params?.source) query.set('source', params.source);
    if (params?.state) query.set('state', params.state);
    if (params?.policy_decision) query.set('policy_decision', params.policy_decision);
    if (params?.diagnosis_category) query.set('diagnosis_category', params.diagnosis_category);
    if (params?.ros_band) query.set('ros_band', params.ros_band);
    if (params?.link_status) query.set('link_status', params.link_status);
    if (params?.limit) query.set('limit', params.limit.toString());
    if (params?.offset) query.set('offset', params.offset.toString());

    return fetchJSON<CaseListResponse>(`/dashboard/cases?${query.toString()}`);
  },

  getCaseDetail: (caseId: string): Promise<CaseDetail> =>
    fetchJSON<CaseDetail>(`/dashboard/cases/${encodeURIComponent(caseId)}`),

  getEvaluationReport: (): Promise<EvaluationReport> =>
    fetchJSON<EvaluationReport>('/dashboard/evaluation'),

  getSettings: (): Promise<SettingsData> => fetchJSON<SettingsData>('/dashboard/settings'),

  getSimulatorScenarios: (): Promise<SimulatorScenario[]> =>
    fetchJSON<SimulatorScenario[]>('/simulator/scenarios'),

  triggerScenario: (scenarioId: string): Promise<TriggerResponse> =>
    fetchJSON<TriggerResponse>('/simulator/trigger', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId }),
    }),

  resetDemoDatabase: (): Promise<{ status: string; message: string }> =>
    fetchJSON<{ status: string; message: string }>('/simulator/reset', {
      method: 'POST',
    }),

  getReminderPreview: (caseId: string, medium: 'sms' | 'email'): Promise<any> =>
    fetchJSON<any>(`/dashboard/cases/${encodeURIComponent(caseId)}/reminder/preview`, {
      method: 'POST',
      body: JSON.stringify({ medium }),
    }),

  sendReminder: (caseId: string, previewToken: string, medium: 'sms' | 'email'): Promise<any> =>
    fetchJSON<any>(`/dashboard/cases/${encodeURIComponent(caseId)}/reminder/send`, {
      method: 'POST',
      body: JSON.stringify({ preview_token: previewToken, medium }),
    }),
};
