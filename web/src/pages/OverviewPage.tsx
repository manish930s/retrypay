import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  DollarSign,
  ExternalLink,
  HelpCircle,
  Radio,
  RefreshCw,
  Send,
  Shield,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { api } from '../api';
import { BatchRecoveryMetrics, OverviewStats } from '../types';

interface OverviewPageProps {
  onSelectCase: (caseId: string) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({ onSelectCase }) => {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [batchMetrics, setBatchMetrics] = useState<BatchRecoveryMetrics | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadOverview();
  }, []);

  const loadOverview = async () => {
    try {
      setLoading(true);
      setError(null);
      const [overviewData, batchData] = await Promise.all([
        api.getOverview(),
        api.getBatchMetrics().catch(() => null),
      ]);
      setStats(overviewData);
      setBatchMetrics(batchData);
    } catch (err: any) {
      setError(err.message || 'Failed to load dashboard telemetry.');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
        <RefreshCw size={22} className="animate-spin" style={{ margin: '0 auto 12px auto', color: 'var(--text-primary)' }} />
        <div style={{ fontSize: '13.5px', fontWeight: 500 }}>Loading operational telemetry...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          padding: '24px',
          background: 'var(--accent-danger-subtle)',
          border: '1px solid var(--accent-danger-border)',
          borderRadius: 'var(--radius-lg)',
          marginTop: '10px',
        }}
      >
        <div style={{ color: 'var(--accent-danger-text)', fontWeight: 600, fontSize: '15px', marginBottom: '6px' }}>
          Failed to connect to ReTryPay API
        </div>
        <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{error}</div>
        <button className="btn btn-secondary" style={{ marginTop: '16px' }} onClick={loadOverview}>
          <RefreshCw size={13} /> Retry Connection
        </button>
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div>
      {/* Page Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 className="page-title">Merchant Recovery Telemetry</h1>
          <p className="page-subtitle">
            Real-time payment event truth, deterministic policy gates, and attributable Test Mode recoveries.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={loadOverview}>
          <RefreshCw size={13} /> Refresh Metrics
        </button>
      </div>

      {/* Measured Batch Recovery Panel (Track 03 Measured Results) */}
      {batchMetrics && (
        <div className="panel" style={{ marginBottom: '24px', background: '#ffffff' }}>
          <div className="panel-header" style={{ marginBottom: '14px' }}>
            <div>
              <h2 className="panel-title" style={{ fontSize: '16px' }}>
                <TrendingUp size={17} color="var(--accent-success-text)" />
                Measured Batch Recovery Results
              </h2>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Live database aggregation across all ingested payment attempts and reconciled recoveries.
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="badge badge-neutral" style={{ fontSize: '10.5px' }}>
                <ShieldCheck size={12} color="var(--accent-success-text)" />
                Live DB Aggregation • Test Mode
              </span>
            </div>
          </div>

          {/* Primary Batch Metric Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px', marginBottom: '16px' }}>
            <div style={{ background: '#f9fafb', border: '1px solid var(--border-subtle)', padding: '14px 16px', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Recovered Cases</span>
                <CheckCircle2 size={14} color="var(--accent-success-text)" />
              </div>
              <div className="mono" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent-success-text)', marginTop: '4px' }}>
                {batchMetrics.recovered_count}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                of {batchMetrics.total_failures_ingested} ingested failures
              </div>
            </div>

            <div style={{ background: '#f9fafb', border: '1px solid var(--border-subtle)', padding: '14px 16px', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Recovered GMV</span>
                <DollarSign size={14} color="var(--text-primary)" />
              </div>
              <div className="mono" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>
                ₹{batchMetrics.recovered_gmv_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Sum of verified recovered orders
              </div>
            </div>

            <div style={{ background: '#f9fafb', border: '1px solid var(--border-subtle)', padding: '14px 16px', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Policy Block Rate</span>
                <Shield size={14} color="var(--accent-danger-text)" />
              </div>
              <div className="mono" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>
                {(batchMetrics.policy_block_rate * 100).toFixed(1)}%
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Gated by hard privacy & safety rules
              </div>
            </div>

            <div style={{ background: '#f9fafb', border: '1px solid var(--border-subtle)', padding: '14px 16px', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Manual Review Rate</span>
                <HelpCircle size={14} color="var(--accent-warning-text)" />
              </div>
              <div className="mono" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>
                {(batchMetrics.manual_review_rate * 100).toFixed(1)}%
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                High-risk / edge routing cases
              </div>
            </div>

            <div style={{ background: '#f9fafb', border: '1px solid var(--border-subtle)', padding: '14px 16px', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Avg Time to Recover</span>
                <Clock size={14} color="var(--accent-info-text)" />
              </div>
              <div className="mono" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent-info-text)', marginTop: '4px' }}>
                {batchMetrics.avg_time_to_recover_seconds > 0 ? `${batchMetrics.avg_time_to_recover_seconds}s` : '—'}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                From failure ingestion to reconciliation
              </div>
            </div>
          </div>

          {/* Real-time State Distribution Breakdown */}
          <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>
              Batch State Distribution:
            </span>
            {Object.entries(batchMetrics.state_distribution).map(([st, cnt]) => (
              <span key={st} className="badge badge-neutral" style={{ fontSize: '10px' }}>
                {st}: <strong style={{ color: 'var(--text-primary)', marginLeft: '3px' }}>{cnt}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* KPI Stats Grid */}
      <div className="grid-stats">
        <div className="stat-card">
          <div className="stat-header">
            <span>Failed Events Ingested</span>
            <div className="stat-icon-ring">
              <Radio size={13} color="var(--text-muted)" />
            </div>
          </div>
          <div className="stat-value">{stats.total_failed_events}</div>
          <div className="stat-subtitle">HMAC verified webhook events</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span>Active Cases</span>
            <div className="stat-icon-ring">
              <Clock size={13} color="var(--text-muted)" />
            </div>
          </div>
          <div className="stat-value">{stats.active_cases_count}</div>
          <div className="stat-subtitle">Currently in recovery pipeline</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span>Verified Recoveries</span>
            <div className="stat-icon-ring" style={{ borderColor: 'var(--accent-success-border)' }}>
              <CheckCircle2 size={13} color="var(--accent-success-text)" />
            </div>
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-success-text)' }}>
            {stats.two_evidence_verified_recoveries}
          </div>
          <div className="stat-subtitle">Two-evidence correlated</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span>Policy Block Rate</span>
            <div className="stat-icon-ring" style={{ borderColor: 'var(--accent-danger-border)' }}>
              <Shield size={13} color="var(--accent-danger-text)" />
            </div>
          </div>
          <div className="stat-value">{(stats.policy_block_rate * 100).toFixed(1)}%</div>
          <div className="stat-subtitle">Deterministic safety gates</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span>Manual Review Rate</span>
            <div className="stat-icon-ring" style={{ borderColor: 'var(--accent-warning-border)' }}>
              <HelpCircle size={13} color="var(--accent-warning-text)" />
            </div>
          </div>
          <div className="stat-value">{(stats.manual_review_rate * 100).toFixed(1)}%</div>
          <div className="stat-subtitle">High-risk & edge routing</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span>Simulated Notifications</span>
            <div className="stat-icon-ring">
              <Send size={13} color="var(--text-muted)" />
            </div>
          </div>
          <div className="stat-value">{stats.simulated_notifications_count}</div>
          <div className="stat-subtitle">Simulated WhatsApp messages</div>
        </div>
      </div>

      {/* Two Column Grid: Pipeline State Breakdown + Recent Cases */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
        {/* State Breakdown Panel */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              <TrendingUp size={16} color="var(--text-primary)" />
              Recovery Pipeline State Breakdown
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {Object.entries(stats.active_cases_by_state).length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '24px 0', textAlign: 'center' }}>
                No active recovery cases. Trigger a scenario from the Webhook Simulator.
              </div>
            ) : (
              Object.entries(stats.active_cases_by_state).map(([st, count]) => {
                const isRecovered = st === 'RECOVERED';
                const isBlocked = st.startsWith('CLOSED') || st === 'EXPIRED';
                const isPending = st === 'PAYMENT_CONFIRMED_PENDING_ATTRIBUTION';
                return (
                  <div
                    key={st}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '8px 12px',
                      background: '#f9fafb',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      fontSize: '13px',
                    }}
                  >
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
                      {st}
                    </span>
                    <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                      {count}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Recent Cases Panel */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              <Clock size={16} color="var(--text-primary)" />
              Recent Recovery Cases
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {stats.recent_cases.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '24px 0', textAlign: 'center' }}>
                No cases recorded yet. Use the simulator to trigger test cases.
              </div>
            ) : (
              stats.recent_cases.map((rc) => (
                <div
                  key={rc.case_id}
                  onClick={() => onSelectCase(rc.case_id)}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '10px 14px',
                    background: '#ffffff',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    cursor: 'pointer',
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--border-medium)';
                    e.currentTarget.style.background = '#f9fafb';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--border-subtle)';
                    e.currentTarget.style.background = '#ffffff';
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: '13px',
                        color: 'var(--text-primary)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                      }}
                    >
                      <span className="mono">{rc.case_id}</span>
                      <ExternalLink size={11} color="var(--text-muted)" />
                    </div>
                    <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      Order <span className="mono">{rc.order_id}</span> • ₹
                      {(rc.amount_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span
                      className={`badge ${
                        rc.state === 'RECOVERED'
                          ? 'badge-success'
                          : rc.state.startsWith('CLOSED')
                          ? 'badge-danger'
                          : 'badge-info'
                      }`}
                    >
                      {rc.state}
                    </span>
                    {rc.ros_score !== null && rc.ros_score !== undefined && (
                      <div className="mono" style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '3px' }}>
                        ROS: {rc.ros_score}/100
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Latest Audit Activity Log */}
      <div className="panel" style={{ padding: '20px 22px' }}>
        <div className="panel-header">
          <h2 className="panel-title">
            <AlertTriangle size={16} color="var(--text-primary)" />
            Sanitized audit event timeline
          </h2>
        </div>
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Case ID</th>
                <th>Event Type</th>
                <th>Transition</th>
                <th>Actor</th>
              </tr>
            </thead>
            <tbody>
              {stats.latest_audit_activity.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '28px' }}>
                    No audit records available.
                  </td>
                </tr>
              ) : (
                stats.latest_audit_activity.map((a) => (
                  <tr key={a.event_id} onClick={() => a.case_id && onSelectCase(a.case_id)}>
                    <td className="mono" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {new Date(a.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      {a.case_id || '—'}
                    </td>
                    <td>
                      <span className="badge badge-neutral">{a.event_type}</span>
                    </td>
                    <td style={{ fontSize: '12px' }}>
                      {a.before_state ? (
                        <span>
                          <span style={{ color: 'var(--text-muted)' }}>{a.before_state}</span>
                          <span style={{ color: 'var(--text-muted)', margin: '0 4px' }}>→</span>
                          <span style={{ color: 'var(--accent-info-text)', fontWeight: 600 }}>
                            {a.after_state}
                          </span>
                        </span>
                      ) : (
                        <span style={{ color: 'var(--accent-info-text)', fontWeight: 600 }}>
                          {a.after_state}
                        </span>
                      )}
                    </td>
                    <td>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                        {a.actor_type}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
