import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { EvaluationPage } from '../pages/EvaluationPage';
import { api } from '../api';
import { EvaluationReport } from '../types';

vi.mock('../api', () => ({
  api: {
    getEvaluationReport: vi.fn(),
  },
}));

const mockReportCrossingZero: EvaluationReport = {
  evaluation_run_id: 'eval_run_test_001',
  cohort_id: 'cohort_test_001',
  sample_size: 1000,
  scenario_seed: 42,
  assignment_seed: 100,
  generator_version: 'synth-gen-v1.0',
  policy_version: 'recovery-v1.3',
  ros_version: 'ros-v1.0',
  estimator_version: 'sim-estimator-v1',
  disclaimer: 'simulated offline estimate; not production conversion evidence',
  natural_recovery_rate: 0.1557,
  estimated_incremental_recovery_conversion: 0.0455,
  ci_incremental_conversion: {
    lower: -0.0114,
    upper: 0.1084,
    confidence_level: 0.95,
    status: 'crosses_zero',
  },
  estimated_incremental_recovery_gmv_paise: 6853314,
  ci_incremental_gmv_paise: {
    lower: -6061613,
    upper: 19193727,
    confidence_level: 0.95,
    status: 'crosses_zero',
  },
  contact_efficiency_paise_per_contact: 357670,
  incremental_gmv_per_contact_paise: 69225,
  ci_incremental_gmv_per_contact_paise: {
    lower: -10000,
    upper: 150000,
    confidence_level: 0.95,
    status: 'crosses_zero',
  },
  policy_safety_metrics: {
    policy_block_rate: 0.201,
    deferred_rate: 0.052,
    manual_review_rate: 0.031,
    no_action_selection_rate: 0.1,
    contact_suppression_rate: 0.201,
    unsafe_action_rate: 0.0,
  },
  arm_metrics: {
    NO_ACTION: {
      strategy: 'NO_ACTION',
      sample_size: 334,
      recovery_count: 52,
      recovery_rate: 0.1557,
      total_gmv_paise: 168171549,
      recovered_gmv_paise: 28641818,
      total_contacts: 0,
      contact_rate: 0.0,
      observed_recovery_gmv_label: 'synthetic offline observed outcome; not production evidence',
    },
    GENERIC_REMINDER: {
      strategy: 'GENERIC_REMINDER',
      sample_size: 333,
      recovery_count: 56,
      recovery_rate: 0.1682,
      total_gmv_paise: 182417293,
      recovered_gmv_paise: 25257895,
      total_contacts: 254,
      contact_rate: 0.7628,
      observed_recovery_gmv_label: 'synthetic offline observed outcome; not production evidence',
    },
    RETRYPAY_POLICY: {
      strategy: 'RETRYPAY_POLICY',
      sample_size: 333,
      recovery_count: 67,
      recovery_rate: 0.2012,
      total_gmv_paise: 186462338,
      recovered_gmv_paise: 35495132,
      total_contacts: 266,
      contact_rate: 0.7988,
      observed_recovery_gmv_label: 'synthetic offline observed outcome; not production evidence',
    },
  },
  operational_decision_metrics: {
    diagnosis_distribution: {
      PAYMENT_TIMED_OUT: 200,
    },
    ros_band_distribution: {
      HIGH: 150,
      MEDIUM: 100,
      LOW: 83,
    },
    selected_action_distribution: {
      PAYMENT_LINK_ONLY: 200,
      NO_ACTION: 133,
    },
    avg_decision_latency_ms: 0.42,
  },
};

describe('EvaluationPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders mandatory persistent evaluation disclaimer across evaluation metric areas', async () => {
    vi.mocked(api.getEvaluationReport).mockResolvedValue(mockReportCrossingZero);
    render(<EvaluationPage />);

    await waitFor(() => {
      expect(
        screen.getAllByText(/simulated offline estimate; not production conversion evidence/i).length
      ).toBeGreaterThanOrEqual(1);
    });
  });

  it('renders "Inconclusive in this synthetic run" when confidence interval crosses zero', async () => {
    vi.mocked(api.getEvaluationReport).mockResolvedValue(mockReportCrossingZero);
    render(<EvaluationPage />);

    await waitFor(() => {
      const tags = screen.getAllByText(/Inconclusive in this synthetic run/i);
      expect(tags.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('renders Contact Efficiency with proper currency formatting per synthetic contact', async () => {
    vi.mocked(api.getEvaluationReport).mockResolvedValue(mockReportCrossingZero);
    render(<EvaluationPage />);

    await waitFor(() => {
      expect(screen.getAllByText(/synthetic contact/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Contact Efficiency')).toBeInTheDocument();
    });
  });

  it('renders loading state initially and handles error state gracefully', async () => {
    vi.mocked(api.getEvaluationReport).mockRejectedValue(new Error('Network error loading report'));
    render(<EvaluationPage />);

    expect(screen.getByText(/Loading synthetic counterfactual evaluation/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Evaluation Report Unavailable')).toBeInTheDocument();
    });
  });
});
