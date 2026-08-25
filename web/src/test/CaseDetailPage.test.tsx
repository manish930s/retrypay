import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CaseDetailPage } from '../pages/CaseDetailPage';
import { api } from '../api';
import { CaseDetail } from '../types';

vi.mock('../api', () => ({
  api: {
    getCaseDetail: vi.fn(),
  },
}));

const mockCaseDetail: CaseDetail = {
  case_id: 'rcv_test_case_999',
  order_id: 'order_test_999',
  state: 'NOTIFIED',
  closure_reason: undefined,
  contact_count: 1,
  created_at: '2026-08-24T10:00:00Z',
  updated_at: '2026-08-24T10:01:00Z',
  customer: {
    customer_id: 'cust_order_test_999',
    masked_phone: '+91******1234',
    masked_email: 'test@example.com',
    successful_purchase_count: 2,
    consents: { WHATSAPP: 'OPTED_IN' },
  },
  order: {
    order_id: 'order_test_999',
    amount_paise: 250000,
    currency: 'INR',
    status: 'attempted',
  },
  payment_attempt: {
    payment_id: 'pay_test_999',
    amount_paise: 250000,
    currency: 'INR',
    status: 'failed',
    method: 'upi',
    error_code: 'BAD_REQUEST_PAYMENT_TIMED_OUT',
    error_description: 'Gateway timed out',
    occurred_at: '2026-08-24T10:00:00Z',
  },
  policy_evaluation: {
    evaluation_id: 'eval_test_999',
    policy_version: 'recovery-v1.3',
    decision_type: 'ELIGIBLE',
    reasons: [],
    evaluated_at: '2026-08-24T10:00:01Z',
  },
  decision_trace: {
    trace_id: 'trace_test_999',
    policy_decision: 'ELIGIBLE',
    ros_score: 72,
    ros_contributions: { base: 60, purchase_history: 12 },
    diagnosis_category: 'PAYMENT_TIMED_OUT',
    diagnosis_confidence: 0.95,
    diagnosis_mode: 'RULES',
    diagnosis_fallback_used: false,
    action_candidates: ['NO_ACTION', 'DISCOUNT_INCENTIVE', 'PAYMENT_LINK_ONLY'],
    selected_action: 'PAYMENT_LINK_ONLY',
    utility_paise: 25000,
    created_at: '2026-08-24T10:00:02Z',
  },
  recovery_action: {
    action_id: 'act_test_999',
    action_type: 'PAYMENT_LINK_ONLY',
    status: 'EXECUTED',
    created_at: '2026-08-24T10:00:03Z',
  },
  payment_link: {
    link_id: 'plink_test_999',
    provider_link_id: 'plink_rzp_test_999',
    reference_id: 'ref_test_999',
    short_url: 'https://rzp.io/i/test999',
    amount_paise: 250000,
    currency: 'INR',
    status: 'created',
    expire_by: '2026-08-25T10:00:00Z',
  },
  notifications: [
    {
      notification_id: 'notif_test_999',
      channel: 'WHATSAPP',
      template_key: 'PAYMENT_RECOVERY_STANDARD',
      masked_recipient: '+91******1234',
      link_reference: 'https://rzp.io/i/test999',
      status: 'SIMULATED_SENT',
      simulated_at: '2026-08-24T10:00:04Z',
    },
  ],
  budget_reservation: {
    reservation_id: 'res_test_999',
    amount_paise: 250000,
    reservation_date: '2026-08-24',
    status: 'COMMITTED',
  },
  timeline: [
    {
      step_number: 1,
      title: 'Payment Failed Event Ingested',
      status: 'info',
      timestamp: '2026-08-24T10:00:00Z',
      description: 'Received failed payment pay_test_999',
      metadata: { method: 'upi' },
    },
    {
      step_number: 2,
      title: 'Deterministic Policy: ELIGIBLE',
      status: 'success',
      timestamp: '2026-08-24T10:00:01Z',
      description: 'Evaluated against rules version recovery-v1.3',
      metadata: {},
    },
  ],
  audit_events: [
    {
      event_id: 'aud_test_999',
      case_id: 'rcv_test_case_999',
      event_type: 'POLICY_EVALUATED',
      actor_type: 'SYSTEM',
      before_state: 'ENRICHING',
      after_state: 'POLICY_EVALUATED',
      safe_reason_code: 'ELIGIBLE_FOR_RECOVERY',
      version_info: 'recovery-v1.3',
      timestamp: '2026-08-24T10:00:01Z',
      sanitized_metadata: { decision_type: 'ELIGIBLE' },
    },
  ],
};

describe('CaseDetailPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders "Sanitized audit event timeline" in tab list and tab content', async () => {
    vi.mocked(api.getCaseDetail).mockResolvedValue(mockCaseDetail);
    render(<CaseDetailPage caseId="rcv_test_case_999" onBack={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Sanitized audit event timeline')).toBeInTheDocument();
    });

    // Click on audit tab
    const auditTabBtn = screen.getByRole('button', { name: /Sanitized audit event timeline/i });
    fireEvent.click(auditTabBtn);

    expect(screen.getAllByText('Sanitized audit event timeline').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('POLICY_EVALUATED').length).toBeGreaterThanOrEqual(1);
  });

  it('does NOT render forbidden sensitive terms or raw secrets in case detail', async () => {
    vi.mocked(api.getCaseDetail).mockResolvedValue(mockCaseDetail);
    const { container } = render(<CaseDetailPage caseId="rcv_test_case_999" onBack={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('rcv_test_case_999')).toBeInTheDocument();
    });

    const pageText = container.textContent?.toLowerCase() || '';
    expect(pageText).not.toContain('raw audit log');
    expect(pageText).not.toContain('webhook_secret');
    expect(pageText).not.toContain('gemini_api_key');
    expect(pageText).not.toContain('raw_body');
    expect(pageText).not.toContain('stack_trace');
  });

  it('renders loading state and error state if case not found', async () => {
    vi.mocked(api.getCaseDetail).mockRejectedValue(new Error('Case not found'));
    render(<CaseDetailPage caseId="nonexistent_id" onBack={vi.fn()} />);

    expect(screen.getByText(/Loading case investigation/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Failed to load case/i)).toBeInTheDocument();
      expect(screen.getByText('Case not found')).toBeInTheDocument();
    });
  });
});
