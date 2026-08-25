import React, { useEffect, useState } from 'react';
import { Filter, RefreshCw, Search, ShieldAlert } from 'lucide-react';
import { api } from '../api';
import { CaseSummary } from '../types';

interface CaseListPageProps {
  onSelectCase: (caseId: string) => void;
}

export const CaseListPage: React.FC<CaseListPageProps> = ({ onSelectCase }) => {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Filters
  const [filterSource, setFilterSource] = useState<string>('');
  const [filterState, setFilterState] = useState<string>('');
  const [filterPolicy, setFilterPolicy] = useState<string>('');
  const [filterRosBand, setFilterRosBand] = useState<string>('');

  useEffect(() => {
    loadCases();
  }, [filterSource, filterState, filterPolicy, filterRosBand]);

  const loadCases = async () => {
    try {
      setLoading(true);
      const res = await api.getCases({
        source: filterSource || undefined,
        state: filterState || undefined,
        policy_decision: filterPolicy || undefined,
        ros_band: filterRosBand || undefined,
        limit: 100,
      });
      setCases(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error('Failed to load cases:', err);
    } finally {
      setLoading(false);
    }
  };

  const filteredCases = cases.filter((c) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      c.case_id.toLowerCase().includes(q) ||
      c.order_id.toLowerCase().includes(q) ||
      (c.masked_customer_email && c.masked_customer_email.toLowerCase().includes(q))
    );
  });

  return (
    <div>
      {/* Page Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Recovery Cases</h1>
          <p className="page-subtitle">Inspect recovery control plane state, policy decisions, and ROS telemetry.</p>
        </div>
        <button className="btn btn-secondary" onClick={loadCases} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Filter & Search Toolbar */}
      <div
        className="panel"
        style={{
          padding: '14px 18px',
          marginBottom: '20px',
          display: 'flex',
          gap: '12px',
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: '1', minWidth: '220px' }}>
          <Search size={15} color="var(--text-muted)" />
          <input
            type="text"
            className="text-input"
            style={{ width: '100%' }}
            placeholder="Search by Case ID, Order ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <Filter size={15} color="var(--text-muted)" />
          <select
            className="select-input"
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
            aria-label="Filter by source"
          >
            <option value="">All Sources</option>
            <option value="RAZORPAY_TEST_MODE">Razorpay Test Mode</option>
            <option value="LOCAL_SIMULATION">Local Simulation</option>
            <option value="FAKE_PROVIDER">Fake Provider</option>
          </select>

          <select
            className="select-input"
            value={filterState}
            onChange={(e) => setFilterState(e.target.value)}
            aria-label="Filter by state"
          >
            <option value="">All States</option>
            <option value="RECOVERED">RECOVERED</option>
            <option value="PAYMENT_CONFIRMED_PENDING_ATTRIBUTION">PENDING ATTRIBUTION</option>
            <option value="NOTIFIED">NOTIFIED</option>
            <option value="LINK_CREATED">LINK_CREATED</option>
            <option value="POLICY_EVALUATED">POLICY_EVALUATED</option>
            <option value="CLOSED_BLOCKED">CLOSED_BLOCKED</option>
            <option value="EXPIRED">EXPIRED</option>
          </select>

          <select
            className="select-input"
            value={filterPolicy}
            onChange={(e) => setFilterPolicy(e.target.value)}
            aria-label="Filter by policy decision"
          >
            <option value="">All Policy Decisions</option>
            <option value="ELIGIBLE">ELIGIBLE</option>
            <option value="BLOCK">BLOCK</option>
            <option value="MANUAL_REVIEW">MANUAL_REVIEW</option>
            <option value="DEFER">DEFER</option>
          </select>

          <select
            className="select-input"
            value={filterRosBand}
            onChange={(e) => setFilterRosBand(e.target.value)}
            aria-label="Filter by ROS band"
          >
            <option value="">All ROS Bands</option>
            <option value="HIGH">HIGH (&gt;65)</option>
            <option value="MEDIUM">MEDIUM (35-65)</option>
            <option value="LOW">LOW (&lt;35)</option>
          </select>
        </div>
      </div>

      {/* Case Data Table */}
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Case ID</th>
              <th>Source</th>
              <th>Order & Amount</th>
              <th>Customer</th>
              <th>State</th>
              <th>Policy Decision</th>
              <th>ROS Score</th>
              <th>Diagnosis</th>
              <th>Action</th>
              <th>Link Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={11} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '36px' }}>
                  <RefreshCw size={20} className="animate-spin" style={{ margin: '0 auto 8px auto', color: 'var(--accent-primary)' }} />
                  <div>Loading recovery cases...</div>
                </td>
              </tr>
            ) : filteredCases.length === 0 ? (
              <tr>
                <td colSpan={11} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '44px 20px' }}>
                  <ShieldAlert size={30} color="var(--text-muted)" style={{ margin: '0 auto 10px auto' }} />
                  <div style={{ fontSize: '13.5px', fontWeight: 500, color: 'var(--text-secondary)' }}>
                    No recovery cases found matching filters.
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Try clearing filters or search query, or dispatch a test case via Webhook Simulator.
                  </div>
                </td>
              </tr>
            ) : (
              filteredCases.map((c) => {
                const isRecovered = c.state === 'RECOVERED';
                const isPending = c.state === 'PAYMENT_CONFIRMED_PENDING_ATTRIBUTION';
                const isBlocked = c.state.startsWith('CLOSED') || c.state === 'EXPIRED';
                const isTestMode = c.source === 'RAZORPAY_TEST_MODE';

                return (
                  <tr key={c.case_id} onClick={() => onSelectCase(c.case_id)}>
                    <td className="mono" style={{ color: 'var(--accent-primary)', fontWeight: 600 }}>
                      {c.case_id}
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          fontSize: '10px',
                          background: isTestMode ? 'rgba(59, 130, 246, 0.12)' : 'rgba(139, 92, 246, 0.12)',
                          color: isTestMode ? '#60a5fa' : '#a78bfa',
                          border: isTestMode ? '1px solid rgba(59, 130, 246, 0.25)' : '1px solid rgba(139, 92, 246, 0.25)',
                        }}
                      >
                        {isTestMode ? 'Razorpay Test' : c.source || 'Local Sim'}
                      </span>
                    </td>
                    <td>
                      <div className="mono" style={{ fontWeight: 600 }}>
                        ₹{(c.amount_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </div>
                      <div className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {c.order_id}
                      </div>
                    </td>
                    <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {c.masked_customer_phone || c.masked_customer_email || 'Anonymous'}
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          isRecovered
                            ? 'badge-success'
                            : isPending
                            ? 'badge-warning'
                            : isBlocked
                            ? 'badge-danger'
                            : 'badge-info'
                        }`}
                      >
                        {c.state}
                      </span>
                    </td>
                    <td>
                      {c.policy_decision ? (
                        <span
                          className={`badge ${
                            c.policy_decision === 'ELIGIBLE'
                              ? 'badge-success'
                              : c.policy_decision === 'DEFER'
                              ? 'badge-warning'
                              : 'badge-danger'
                          }`}
                        >
                          {c.policy_decision}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td>
                      {c.ros_score !== null && c.ros_score !== undefined ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <span
                            className="mono"
                            style={{
                              fontWeight: 700,
                              color: c.ros_score >= 65 ? 'var(--accent-success-text)' : c.ros_score >= 35 ? 'var(--accent-warning-text)' : 'var(--accent-danger-text)',
                            }}
                          >
                            {c.ros_score}
                          </span>
                          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>({c.ros_band})</span>
                        </div>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td style={{ fontSize: '12px', maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.diagnosis_category || '—'}
                    </td>
                    <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {c.selected_action || '—'}
                    </td>
                    <td>
                      {c.link_status ? (
                        <div>
                          <span className={`badge ${c.link_status === 'paid' ? 'badge-success' : 'badge-neutral'}`}>
                            {c.link_status}
                          </span>
                          {c.masked_link_id && (
                            <div className="mono" style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              {c.masked_link_id}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {new Date(c.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: '14px', color: 'var(--text-muted)', fontSize: '12px', textAlign: 'right' }}>
        Showing {filteredCases.length} of {total} cases
      </div>
    </div>
  );
};
