import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SimulatorPage } from '../pages/SimulatorPage';
import { api } from '../api';
import { SimulatorScenario, TriggerResponse } from '../types';

vi.mock('../api', () => ({
  api: {
    getSimulatorScenarios: vi.fn(),
    triggerScenario: vi.fn(),
    resetSimulator: vi.fn(),
  },
}));

const mockScenarios: SimulatorScenario[] = [
  {
    id: '1_policy_block_missing_consent',
    title: '1. Policy Block: Missing Customer Consent',
    category: 'Policy Gating',
    description: 'Dispatches payment.failed for an unconsented customer.',
    expected_state: 'CLOSED_BLOCKED',
    expected_closure_reason: 'POLICY_BLOCKED',
  },
  {
    id: '12_high_risk_manual_review',
    title: '12. High-Risk / Hard-Decline Manual Review',
    category: 'Risk & Fraud',
    description: 'Simulates failure with error code SUSPECTED_FRAUD for a consented customer.',
    expected_state: 'MANUAL_REVIEW',
    expected_closure_reason: undefined,
  },
];

const mockHighRiskTriggerResponse: TriggerResponse = {
  scenario_id: '12_high_risk_manual_review',
  title: '12. High-Risk / Hard-Decline Manual Review',
  status: 'success',
  case_id: 'rcv_fraud_test_001',
  order_id: 'order_fraud_test_001',
  final_case_state: 'MANUAL_REVIEW',
  closure_reason: undefined,
  steps_executed: [
    {
      name: 'payment.failed dispatched',
      status_code: 200,
      response: { status: 'processed' },
    },
  ],
  audit_trail: [],
};

describe('SimulatorPage Component & High-Risk Routing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('identifies local signed-webhook simulator in test/demo mode', async () => {
    vi.mocked(api.getSimulatorScenarios).mockResolvedValue(mockScenarios);
    render(<SimulatorPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Local Signed-Webhook Simulator')).toBeInTheDocument();
      expect(
        screen.getByText(/Test Mode webhook fixture dispatcher/i)
      ).toBeInTheDocument();
    });
  });

  it('displays High-Risk scenario label as "High-Risk / Hard-Decline Manual Review" and renders MANUAL_REVIEW state', async () => {
    vi.mocked(api.getSimulatorScenarios).mockResolvedValue(mockScenarios);
    vi.mocked(api.triggerScenario).mockResolvedValue(mockHighRiskTriggerResponse);

    render(<SimulatorPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      expect(
        screen.getByText('12. High-Risk / Hard-Decline Manual Review')
      ).toBeInTheDocument();
    });

    // Select the second scenario item from the list
    const scenarioItem = screen.getByText('12. High-Risk / Hard-Decline Manual Review');
    fireEvent.click(scenarioItem);

    // Click the Trigger button
    const triggerBtn = screen.getByRole('button', { name: /Trigger Simulation Scenario/i });
    fireEvent.click(triggerBtn);

    await waitFor(() => {
      expect(api.triggerScenario).toHaveBeenCalledWith('12_high_risk_manual_review');
      expect(screen.getAllByText('MANUAL_REVIEW').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Execution Result')).toBeInTheDocument();
    });
  });
});
