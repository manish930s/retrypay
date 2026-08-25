import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CaseListPage } from '../pages/CaseListPage';
import { api } from '../api';
import { CaseListResponse } from '../types';

vi.mock('../api', () => ({
  api: {
    getCases: vi.fn(),
  },
}));

const mockCaseList: CaseListResponse = {
  items: [
    {
      case_id: 'rcv_case_001',
      order_id: 'order_001',
      amount_paise: 150000,
      currency: 'INR',
      masked_customer_phone: '+91******1111',
      state: 'RECOVERED',
      closure_reason: 'RECOVERED_VIA_LINK',
      policy_decision: 'ELIGIBLE',
      ros_score: 85,
      ros_band: 'HIGH',
      diagnosis_category: 'PAYMENT_TIMED_OUT',
      selected_action: 'PAYMENT_LINK_ONLY',
      link_status: 'paid',
      contact_count: 1,
      created_at: '2026-08-24T10:00:00Z',
      updated_at: '2026-08-24T10:05:00Z',
    },
    {
      case_id: 'rcv_case_002',
      order_id: 'order_002',
      amount_paise: 300000,
      currency: 'INR',
      masked_customer_phone: '+91******2222',
      state: 'CLOSED_BLOCKED',
      closure_reason: 'POLICY_BLOCKED',
      policy_decision: 'BLOCK',
      ros_score: 0,
      ros_band: 'LOW',
      diagnosis_category: 'UNKNOWN',
      selected_action: 'NO_ACTION',
      link_status: undefined,
      contact_count: 0,
      created_at: '2026-08-24T10:01:00Z',
      updated_at: '2026-08-24T10:01:01Z',
    },
  ],
  total: 2,
  limit: 15,
  offset: 0,
};

describe('CaseListPage Component & Filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders case list table with items and statistics', async () => {
    vi.mocked(api.getCases).mockResolvedValue(mockCaseList);
    render(<CaseListPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('rcv_case_001')).toBeInTheDocument();
      expect(screen.getByText('rcv_case_002')).toBeInTheDocument();
      expect(screen.getAllByText('RECOVERED').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('CLOSED_BLOCKED').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('handles state and ROS band filter selection', async () => {
    vi.mocked(api.getCases).mockResolvedValue(mockCaseList);
    render(<CaseListPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('rcv_case_001')).toBeInTheDocument();
    });

    const stateSelect = screen.getByDisplayValue('All States');
    fireEvent.change(stateSelect, { target: { value: 'RECOVERED' } });

    await waitFor(() => {
      expect(api.getCases).toHaveBeenCalledWith(
        expect.objectContaining({ state: 'RECOVERED' })
      );
    });

    const rosSelect = screen.getByDisplayValue('All ROS Bands');
    fireEvent.change(rosSelect, { target: { value: 'HIGH' } });

    await waitFor(() => {
      expect(api.getCases).toHaveBeenCalledWith(
        expect.objectContaining({ ros_band: 'HIGH' })
      );
    });
  });

  it('renders empty state when no cases match filter criteria', async () => {
    vi.mocked(api.getCases).mockResolvedValue({ items: [], total: 0, limit: 15, offset: 0 });
    render(<CaseListPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/No recovery cases found/i)).toBeInTheDocument();
    });
  });

  it('verifies Synthetic Evaluation is excluded from source filter dropdown', async () => {
    vi.mocked(api.getCases).mockResolvedValue(mockCaseList);
    render(<CaseListPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      const sourceSelect = screen.getByDisplayValue('All Sources');
      expect(sourceSelect).toBeInTheDocument();
      expect(screen.queryByRole('option', { name: 'Synthetic Evaluation' })).not.toBeInTheDocument();
    });
  });

  it('renders source badges and masked link identifiers without exposing raw short_url', async () => {
    const caseWithSourceAndLink: CaseListResponse = {
      items: [
        {
          case_id: 'rcv_case_source_1',
          order_id: 'order_source_1',
          source: 'RAZORPAY_TEST_MODE',
          amount_paise: 250000,
          currency: 'INR',
          masked_customer_phone: '+91******3333',
          state: 'LINK_CREATED',
          policy_decision: 'ELIGIBLE',
          ros_score: 90,
          ros_band: 'HIGH',
          diagnosis_category: 'PAYMENT_TIMED_OUT',
          selected_action: 'PAYMENT_LINK_ONLY',
          link_status: 'created',
          masked_link_id: 'plink_***5678',
          contact_count: 0,
          created_at: '2026-08-24T10:00:00Z',
          updated_at: '2026-08-24T10:00:00Z',
        },
      ],
      total: 1,
      limit: 15,
      offset: 0,
    };
    vi.mocked(api.getCases).mockResolvedValue(caseWithSourceAndLink);
    render(<CaseListPage onSelectCase={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Razorpay Test')).toBeInTheDocument();
      expect(screen.queryByText(/https:\/\/api\.razorpay\.com\/v1\/payment_links/i)).not.toBeInTheDocument();
    });
  });
});
