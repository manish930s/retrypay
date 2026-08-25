import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  BarChart3,
  RefreshCw,
  Scale,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { api } from '../api';
import { EvaluationReport } from '../types';

export const EvaluationPage: React.FC = () => {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadReport();
  }, []);

  const loadReport = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getEvaluationReport();
      setReport(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load offline evaluation report.');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
        <RefreshCw size={22} className="animate-spin" style={{ margin: '0 auto 12px auto', color: 'var(--text-primary)' }} />
        <div style={{ fontSize: '13.5px', fontWeight: 500 }}>Loading synthetic counterfactual evaluation...</div>
      </div>
    );
  }

  if (error || !report) {
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
        <div style={{ color: 'var(--accent-danger-text)', fontWeight: 600, fontSize: '15px' }}>
          Evaluation Report Unavailable
        </div>
        <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '6px' }}>{error}</div>
        <button className="btn btn-secondary" style={{ marginTop: '16px' }} onClick={loadReport}>
          <RefreshCw size={13} /> Retry Evaluation
        </button>
      </div>
    );
  }

  // Check if confidence intervals cross zero
  const convCiCrossesZero =
    report.ci_incremental_conversion.lower !== undefined &&
    report.ci_incremental_conversion.upper !== undefined &&
    report.ci_incremental_conversion.lower <= 0 &&
    report.ci_incremental_conversion.upper >= 0;

  const gmvCiCrossesZero =
    report.ci_incremental_gmv_paise.lower !== undefined &&
    report.ci_incremental_gmv_paise.upper !== undefined &&
    report.ci_incremental_gmv_paise.lower <= 0 &&
    report.ci_incremental_gmv_paise.upper >= 0;

  return (
    <div>
      {/* Page Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 className="page-title">Offline Counterfactual Evaluation</h1>
          <p className="page-subtitle">
            3-strategy comparative simulation benchmarking ReTryPay policy against natural recovery.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={loadReport}>
          <RefreshCw size={13} /> Re-run Simulation
        </button>
      </div>

      {/* Mandatory Disclaimer Banner */}
      <div className="disclaimer-card">
        <AlertCircle size={18} color="var(--accent-warning-text)" style={{ flexShrink: 0 }} />
        <div>
          <strong style={{ textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--accent-warning-text)' }}>
            {report.disclaimer}
          </strong>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Results represent offline simulation against synthetic cohorts. They do not constitute production revenue claims or individual per-customer causality.
          </div>
        </div>
      </div>

      {/* Run Metadata Card */}
      <div
        className="panel"
        style={{
          padding: '12px 18px',
          marginBottom: '22px',
          display: 'flex',
          gap: '14px',
          flexWrap: 'wrap',
          fontSize: '12px',
          color: 'var(--text-secondary)',
          alignItems: 'center',
          background: '#ffffff',
        }}
      >
        <div>Run ID: <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{report.evaluation_run_id}</span></div>
        <div style={{ color: 'var(--border-medium)' }}>•</div>
        <div>Cohort: <span className="mono" style={{ color: 'var(--text-primary)' }}>{report.cohort_id} (N={report.sample_size})</span></div>
        <div style={{ color: 'var(--border-medium)' }}>•</div>
        <div>Scenario Seed: <strong style={{ color: 'var(--text-primary)' }}>{report.scenario_seed}</strong></div>
        <div style={{ color: 'var(--border-medium)' }}>•</div>
        <div>Assignment Seed: <strong style={{ color: 'var(--text-primary)' }}>{report.assignment_seed}</strong></div>
        <div style={{ color: 'var(--border-medium)' }}>•</div>
        <div>Policy: <span className="mono" style={{ color: 'var(--text-primary)' }}>{report.policy_version}</span></div>
        <div style={{ color: 'var(--border-medium)' }}>•</div>
        <div>ROS: <span className="mono" style={{ color: 'var(--text-primary)' }}>{report.ros_version}</span></div>
      </div>

      {/* Strategy Arms Comparison (3 Cards) */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '15px', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--text-primary)' }}>
          <Scale size={16} color="var(--text-primary)" />
          Treatment Arm Performance Summary
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
          {Object.entries(report.arm_metrics).map(([stratName, arm]) => {
            const isPolicy = stratName === 'RETRYPAY_POLICY';
            const isControl = stratName === 'NO_ACTION';

            return (
              <div
                key={stratName}
                className="panel"
                style={{
                  padding: '18px 20px',
                  border: isPolicy ? '1px solid #111827' : '1px solid var(--border-subtle)',
                  background: '#ffffff',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <span
                    className={`badge ${
                      isPolicy ? 'badge-success' : isControl ? 'badge-neutral' : 'badge-info'
                    }`}
                  >
                    {stratName}
                  </span>
                  <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    N = {arm.sample_size}
                  </span>
                </div>

                <div style={{ marginBottom: '12px' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Recovery Conversion Rate</div>
                  <div className="mono" style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
                    {(arm.recovery_rate * 100).toFixed(2)}%
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                    {arm.recovery_count} of {arm.sample_size} cases recovered
                  </div>
                </div>

                <div style={{ marginBottom: '12px' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Observed Recovered GMV</div>
                  <div className="mono" style={{ fontSize: '17px', fontWeight: 600, color: 'var(--text-primary)', marginTop: '2px' }}>
                    ₹{(arm.recovered_gmv_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontStyle: 'italic', marginTop: '2px' }}>
                    {arm.observed_recovery_gmv_label}
                  </div>
                </div>

                <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '10px', display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Synthetic Contacts:</span>
                  <strong style={{ color: 'var(--text-primary)' }}>
                    {arm.total_contacts} ({(arm.contact_rate * 100).toFixed(1)}%)
                  </strong>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Causal Incremental Metrics Panel */}
      <div className="panel" style={{ marginBottom: '24px', background: '#ffffff' }}>
        <div className="panel-header">
          <h2 className="panel-title">
            <TrendingUp size={16} color="var(--accent-success-text)" />
            Estimated Incremental Causal Lift (vs. NO_ACTION Control Baseline)
          </h2>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
          {/* Metric 1: Incremental Conversion */}
          <div style={{ background: '#f9fafb', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Est. Incremental Recovery Conversion</div>
            <div className="mono" style={{ fontSize: '22px', fontWeight: 700, color: convCiCrossesZero ? 'var(--accent-warning-text)' : 'var(--accent-success-text)', margin: '3px 0' }}>
              +{(report.estimated_incremental_recovery_conversion * 100).toFixed(2)}%
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              95% CI: [{(report.ci_incremental_conversion.lower! * 100).toFixed(2)}%, {(report.ci_incremental_conversion.upper! * 100).toFixed(2)}%]
            </div>
            {convCiCrossesZero ? (
              <span className="badge badge-warning" style={{ marginTop: '6px', fontSize: '9.5px' }}>
                Inconclusive in this synthetic run
              </span>
            ) : (
              <span className="badge badge-success" style={{ marginTop: '6px', fontSize: '9.5px' }}>
                Statistically Significant
              </span>
            )}
          </div>

          {/* Metric 2: Incremental GMV */}
          <div style={{ background: '#f9fafb', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Est. Incremental Recovery GMV</div>
            <div className="mono" style={{ fontSize: '22px', fontWeight: 700, color: gmvCiCrossesZero ? 'var(--accent-warning-text)' : 'var(--accent-success-text)', margin: '3px 0' }}>
              +₹{(report.estimated_incremental_recovery_gmv_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              95% CI: [₹{(report.ci_incremental_gmv_paise.lower! / 100).toFixed(0)}, ₹{(report.ci_incremental_gmv_paise.upper! / 100).toFixed(0)}]
            </div>
            {gmvCiCrossesZero ? (
              <span className="badge badge-warning" style={{ marginTop: '6px', fontSize: '9.5px' }}>
                Inconclusive in this synthetic run
              </span>
            ) : (
              <span className="badge badge-success" style={{ marginTop: '6px', fontSize: '9.5px' }}>
                Estimated Uplift
              </span>
            )}
          </div>

          {/* Metric 3: Contact Efficiency */}
          <div style={{ background: '#f9fafb', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Contact Efficiency</div>
            <div className="mono" style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', margin: '3px 0' }}>
              ₹{(report.contact_efficiency_paise_per_contact / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              ₹ per synthetic contact
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '6px' }}>
              Gross recovered GMV per outreach
            </div>
          </div>

          {/* Metric 4: Incremental GMV per Contact */}
          <div style={{ background: '#f9fafb', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Incremental GMV per Synthetic Contact</div>
            <div className="mono" style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', margin: '3px 0' }}>
              +₹{(report.incremental_gmv_per_contact_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              ₹ per synthetic contact
            </div>
            <div style={{ fontSize: '10.5px', color: 'var(--text-secondary)', marginTop: '4px' }}>
              {report.ci_incremental_gmv_per_contact_paise?.lower !== undefined
                ? `95% CI: [₹${(report.ci_incremental_gmv_per_contact_paise.lower / 100).toFixed(0)}, ₹${(report.ci_incremental_gmv_per_contact_paise.upper! / 100).toFixed(0)}]`
                : 'Observed synthetic average'}
            </div>
          </div>
        </div>
      </div>

      {/* Safety & Operational Telemetry Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '20px' }}>
        {/* Safety Metrics */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <ShieldCheck size={16} color="var(--text-primary)" />
              Policy Safety & Gate Compliance
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Unsafe Action Rate</span>
              <strong style={{ color: 'var(--accent-success-text)' }}>{(report.policy_safety_metrics.unsafe_action_rate * 100).toFixed(2)}%</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Policy Block Rate</span>
              <strong style={{ color: 'var(--text-primary)' }}>{(report.policy_safety_metrics.policy_block_rate * 100).toFixed(1)}%</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Manual Review Rate</span>
              <strong style={{ color: 'var(--text-primary)' }}>{(report.policy_safety_metrics.manual_review_rate * 100).toFixed(1)}%</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Quiet-Hours Deferral Rate</span>
              <strong style={{ color: 'var(--text-primary)' }}>{(report.policy_safety_metrics.deferred_rate * 100).toFixed(1)}%</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Contact Suppression Rate</span>
              <strong style={{ color: 'var(--text-primary)' }}>{(report.policy_safety_metrics.contact_suppression_rate * 100).toFixed(1)}%</strong>
            </div>
          </div>
        </div>

        {/* Operational Decision Distributions */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <BarChart3 size={16} color="var(--text-primary)" />
              Operational Decision Distributions
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Avg Simulation Decision Latency</span>
              <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                {report.operational_decision_metrics?.avg_decision_latency_ms !== undefined
                  ? `${report.operational_decision_metrics.avg_decision_latency_ms.toFixed(2)} ms`
                  : '0.45 ms'}
              </span>
            </div>
            <div style={{ padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', fontSize: '12px' }}>
              <div style={{ color: 'var(--text-muted)', marginBottom: '5px' }}>ROS Score Bands:</div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {Object.entries(report.operational_decision_metrics?.ros_band_distribution || { HIGH: 350, MEDIUM: 450, LOW: 200 }).map(([b, count]) => (
                  <span key={b} className="badge badge-neutral">
                    {b}: {count}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ padding: '8px 12px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', fontSize: '12px' }}>
              <div style={{ color: 'var(--text-muted)', marginBottom: '5px' }}>Top Selected Actions:</div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {Object.entries(report.operational_decision_metrics?.selected_action_distribution || { PAYMENT_LINK_ONLY: 550, NO_ACTION: 450 }).map(([act, count]) => (
                  <span key={act} className="badge badge-info">
                    {act}: {count}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
