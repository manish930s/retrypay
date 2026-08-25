import React, { useEffect, useState } from 'react';
import {
  CheckCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { api } from '../api';
import { SimulatorScenario, TriggerResponse } from '../types';

interface SimulatorPageProps {
  onSelectCase: (caseId: string) => void;
}

export const SimulatorPage: React.FC<SimulatorPageProps> = ({ onSelectCase }) => {
  const [scenarios, setScenarios] = useState<SimulatorScenario[]>([]);
  const [selectedId, setSelectedId] = useState<string>('2_eligible_outreach_flow');
  const [executing, setExecuting] = useState<boolean>(false);
  const [result, setResult] = useState<TriggerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    loadScenarios();
  }, []);

  const loadScenarios = async () => {
    try {
      setLoading(true);
      const data = await api.getSimulatorScenarios();
      setScenarios(data);
      if (data.length > 0) {
        setSelectedId(data[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load simulator scenarios.');
    } finally {
      setLoading(false);
    }
  };

  const handleTrigger = async () => {
    if (!selectedId) return;
    try {
      setExecuting(true);
      setError(null);
      const res = await api.triggerScenario(selectedId);
      setResult(res);
    } catch (err: any) {
      setError(err.message || 'Simulation execution failed.');
    } finally {
      setExecuting(false);
    }
  };

  const selectedScenario = scenarios.find((s) => s.id === selectedId);

  return (
    <div>
      {/* Page Header */}
      <div className="page-header">
        <h1 className="page-title">Local Signed-Webhook Simulator</h1>
        <p className="page-subtitle">
          Test Mode webhook fixture dispatcher. Signs payloads locally and validates deterministic state machine transitions.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.25fr', gap: '20px' }}>
        {/* Left Column: Scenario Selector */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <Terminal size={16} color="var(--text-primary)" />
              Select Test Scenario ({scenarios.length})
            </h2>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '560px', overflowY: 'auto' }}>
            {loading ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '30px', textAlign: 'center' }}>
                <RefreshCw size={18} className="animate-spin" style={{ margin: '0 auto 8px auto', color: 'var(--text-primary)' }} />
                <div>Loading scenarios...</div>
              </div>
            ) : scenarios.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '24px', textAlign: 'center' }}>
                No scenarios available.
              </div>
            ) : (
              scenarios.map((s) => {
                const isSelected = s.id === selectedId;
                return (
                  <div
                    key={s.id}
                    onClick={() => setSelectedId(s.id)}
                    style={{
                      padding: '11px 13px',
                      background: isSelected ? '#f3f4f6' : '#ffffff',
                      border: isSelected ? '1px solid #111827' : '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      cursor: 'pointer',
                      transition: 'all var(--transition-fast)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontWeight: 600, fontSize: '13px', color: '#111827' }}>
                        {s.title}
                      </span>
                      <span className="badge badge-neutral" style={{ fontSize: '9.5px' }}>
                        {s.category}
                      </span>
                    </div>
                    <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                      Expected: <span className="mono" style={{ color: 'var(--accent-info-text)', fontWeight: 500 }}>{s.expected_state}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Execution Inspector */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Scenario Details & Action */}
          {selectedScenario && (
            <div className="panel" style={{ background: '#ffffff' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span className="badge badge-info">{selectedScenario.category}</span>
                <span className="mono badge badge-neutral" style={{ fontSize: '10px' }}>ID: {selectedScenario.id}</span>
              </div>
              <h2 style={{ fontSize: '17px', fontWeight: 700, marginBottom: '8px', color: 'var(--text-primary)' }}>
                {selectedScenario.title}
              </h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.5 }}>
                {selectedScenario.description}
              </p>

              <div
                style={{
                  background: '#f9fafb',
                  border: '1px solid var(--border-subtle)',
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-md)',
                  marginBottom: '18px',
                  fontSize: '12.5px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span style={{ color: 'var(--text-secondary)' }}>Expected Case State:</span>
                <span className="badge badge-success">{selectedScenario.expected_state}</span>
              </div>

              <div
                style={{
                  fontSize: '11.5px',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  marginBottom: '14px',
                }}
              >
                <ShieldCheck size={13} color="var(--accent-success-text)" />
                <span>Signs payloads locally using test HMAC secret; zero external network calls.</span>
              </div>

              <button
                className="btn btn-primary"
                style={{ width: '100%', padding: '10px 16px', fontSize: '13.5px' }}
                onClick={handleTrigger}
                disabled={executing}
              >
                <Play size={15} className={executing ? 'animate-pulse' : ''} />
                <span>{executing ? 'Executing Webhook Simulation...' : 'Trigger Simulation Scenario'}</span>
              </button>
            </div>
          )}

          {/* Execution Error Log */}
          {error && (
            <div
              style={{
                background: 'var(--accent-danger-subtle)',
                border: '1px solid var(--accent-danger-border)',
                borderRadius: 'var(--radius-md)',
                padding: '14px 16px',
                color: 'var(--accent-danger-text)',
                fontSize: '13px',
              }}
            >
              {error}
            </div>
          )}

          {/* Execution Result Log */}
          {result && (
            <div className="panel" style={{ background: '#ffffff' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                <h3 style={{ fontSize: '14.5px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--text-primary)' }}>
                  <CheckCircle size={16} color="var(--accent-success-text)" />
                  Execution Result
                </h3>
                <span className={`badge ${result.status === 'success' ? 'badge-success' : 'badge-danger'}`}>
                  {result.status.toUpperCase()}
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '14px', fontSize: '12px' }}>
                <div style={{ background: '#f9fafb', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ color: 'var(--text-muted)' }}>Created / Matched Case</div>
                  {result.case_id ? (
                    <div
                      className="mono"
                      onClick={() => onSelectCase(result.case_id!)}
                      style={{ color: 'var(--text-primary)', fontWeight: 600, marginTop: '2px', cursor: 'pointer', textDecoration: 'underline' }}
                    >
                      {result.case_id} →
                    </div>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>None (Rejected/Blocked)</span>
                  )}
                </div>

                <div style={{ background: '#f9fafb', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ color: 'var(--text-muted)' }}>Final Case State</div>
                  <span className="badge badge-info" style={{ marginTop: '3px' }}>
                    {result.final_case_state || 'None'}
                  </span>
                </div>
              </div>

              {/* Steps Log */}
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                  Dispatched Webhook Steps:
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  {result.steps_executed.map((st, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        background: '#f9fafb',
                        padding: '7px 10px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '12px',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      <span>{st.name}</span>
                      <span className={`badge ${st.status_code === 200 ? 'badge-success' : 'badge-danger'}`}>
                        HTTP {st.status_code}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Audit trail preview */}
              {result.audit_trail.length > 0 && (
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                    Audit Events Appended:
                  </div>
                  <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
                    {result.audit_trail.map((a, i) => (
                      <span key={i} className="badge badge-neutral" style={{ fontSize: '9.5px' }}>
                        {a.event_type}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
