import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../App';

vi.mock('../api', () => ({
  api: {
    getOverview: vi.fn().mockResolvedValue({
      total_failed_events: 10,
      active_cases_count: 3,
      active_cases_by_state: { RECOVERED: 2, NOTIFIED: 1 },
      total_recovered_cases: 2,
      two_evidence_verified_recoveries: 2,
      policy_block_rate: 0.15,
      manual_review_rate: 0.05,
      deferred_rate: 0.02,
      no_action_selection_rate: 0.1,
      simulated_notifications_count: 4,
      latest_audit_activity: [
        {
          event_id: 'aud_test_1',
          case_id: 'rcv_test_001',
          event_type: 'CASE_CREATED',
          actor_type: 'SYSTEM',
          before_state: null,
          after_state: 'RECEIVED',
          timestamp: '2026-08-24T10:00:00Z',
          sanitized_metadata: { order_id: 'order_123' },
        },
      ],
      recent_cases: [],
    }),
  },
}));

describe('App Root Layout & Safety Banners', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders persistent local-demo safety banner', async () => {
    render(<App />);

    expect(
      screen.getByText(/Local demo operator console — not production authenticated/i)
    ).toBeInTheDocument();
  });

  it('renders navigation sidebar and branding', async () => {
    render(<App />);

    expect(screen.getByText('ReTryPay')).toBeInTheDocument();
    expect(screen.getByText('Operator Console')).toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Recovery Cases')).toBeInTheDocument();
    expect(screen.getByText('Causal Evaluation')).toBeInTheDocument();
    expect(screen.getByText('Webhook Simulator')).toBeInTheDocument();
    expect(screen.getByText('Policy & Guardrails')).toBeInTheDocument();
    expect(screen.getByText('Reset Demo State')).toBeInTheDocument();
  });
});
