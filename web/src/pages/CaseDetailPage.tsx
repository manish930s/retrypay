import React, { useEffect, useState } from 'react';
import {
  ArrowLeft,
  Clock,
  CreditCard,
  FileCode,
  Link,
  RefreshCw,
  Send,
  Shield,
  User,
  Zap,
} from 'lucide-react';
import { api } from '../api';
import { CaseDetail } from '../types';

interface CaseDetailPageProps {
  caseId: string;
  onBack: () => void;
}

export const CaseDetailPage: React.FC<CaseDetailPageProps> = ({ caseId, onBack }) => {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'timeline' | 'policy' | 'ros' | 'link' | 'audit'>('timeline');

  // Reminder Workflow State
  const [showReminderModal, setShowReminderModal] = useState<boolean>(false);
  const [reminderMedium, setReminderMedium] = useState<'sms' | 'email'>('sms');
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);
  const [previewData, setPreviewData] = useState<any | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sendingReminder, setSendingReminder] = useState<boolean>(false);
  const [reminderSendError, setReminderSendError] = useState<string | null>(null);

  useEffect(() => {
    loadDetail();
  }, [caseId]);

  const loadDetail = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getCaseDetail(caseId);
      setDetail(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch case detail.');
    } finally {
      setLoading(false);
    }
  };

  const fetchPreview = async (medium: 'sms' | 'email') => {
    try {
      setPreviewLoading(true);
      setPreviewError(null);
      setPreviewData(null);
      const res = await api.getReminderPreview(caseId, medium);
      setPreviewData(res);
    } catch (err: any) {
      setPreviewError(err.message || 'Failed to fetch reminder preview.');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSendReminder = async () => {
    if (!previewData?.preview_token) return;
    try {
      setSendingReminder(true);
      setReminderSendError(null);
      await api.sendReminder(caseId, previewData.preview_token, reminderMedium);
      setShowReminderModal(false);
      setPreviewData(null);
      await loadDetail();
    } catch (err: any) {
      setReminderSendError(err.message || 'Failed to send reminder.');
    } finally {
      setSendingReminder(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
        <RefreshCw size={22} className="animate-spin" style={{ margin: '0 auto 12px auto', color: 'var(--text-primary)' }} />
        <div style={{ fontSize: '13.5px', fontWeight: 500 }}>Loading case investigation...</div>
      </div>
    );
  }

  if (error || !detail) {
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
          Failed to load case {caseId}
        </div>
        <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '6px' }}>{error}</div>
        <button className="btn btn-secondary" style={{ marginTop: '16px' }} onClick={onBack}>
          <ArrowLeft size={13} /> Back to Case List
        </button>
      </div>
    );
  }

  const isRecovered = detail.state === 'RECOVERED';
  const isPending = detail.state === 'PAYMENT_CONFIRMED_PENDING_ATTRIBUTION';
  const isBlocked = detail.state.startsWith('CLOSED') || detail.state === 'EXPIRED';

  return (
    <div>
      {/* Top Navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <button className="btn btn-secondary" onClick={onBack}>
          <ArrowLeft size={13} /> Back to Case List
        </button>
        <button className="btn btn-secondary" onClick={loadDetail}>
          <RefreshCw size={13} /> Refresh Case
        </button>
      </div>

      {/* Hero Header */}
      <div
        className="panel"
        style={{
          marginBottom: '20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
            <h1 className="page-title mono" style={{ margin: 0, fontSize: '20px' }}>
              {detail.case_id}
            </h1>
            <span
              className="badge"
              style={{
                fontSize: '10.5px',
                background: detail.source === 'RAZORPAY_TEST_MODE' ? '#eff6ff' : '#f5f3ff',
                color: detail.source === 'RAZORPAY_TEST_MODE' ? '#1d4ed8' : '#6d28d9',
                border: detail.source === 'RAZORPAY_TEST_MODE' ? '1px solid #bfdbfe' : '1px solid #ddd6fe',
              }}
            >
              {detail.source === 'RAZORPAY_TEST_MODE' ? 'Razorpay Test Mode' : detail.source || 'Local Simulation'}
            </span>
            <span
              className={`badge ${
                isRecovered ? 'badge-success' : isPending ? 'badge-warning' : isBlocked ? 'badge-danger' : 'badge-info'
              }`}
            >
              {detail.state}
            </span>
            {detail.closure_reason && (
              <span className="badge badge-neutral" style={{ textTransform: 'none' }}>
                Reason: {detail.closure_reason}
              </span>
            )}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            Associated Order: <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{detail.order_id}</span> • Created at{' '}
            {new Date(detail.created_at).toLocaleString()}
          </div>
        </div>

        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Order Amount
          </div>
          <div className="mono" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)' }}>
            ₹{(detail.order.amount_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
        </div>
      </div>

      {/* Context Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '20px' }}>
        {/* Customer Context */}
        <div className="panel" style={{ padding: '16px 18px', background: '#ffffff' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--text-primary)', fontWeight: 600, fontSize: '13px', marginBottom: '10px' }}>
            <User size={15} color="var(--text-muted)" /> Customer Context
          </div>
          <div style={{ fontSize: '12.5px', display: 'flex', flexDirection: 'column', gap: '6px', color: 'var(--text-secondary)' }}>
            <div>ID: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.customer.customer_id}</span></div>
            <div>Phone: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.customer.masked_phone || 'Not provided'}</span></div>
            <div>Email: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.customer.masked_email || 'Not provided'}</span></div>
            <div>Prior Purchases: <strong style={{ color: 'var(--text-primary)' }}>{detail.customer.successful_purchase_count ?? 0}</strong></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>WhatsApp Consent:</span>
              <span className={`badge ${detail.customer.consents?.whatsapp === 'OPTED_IN' ? 'badge-success' : 'badge-danger'}`}>
                {detail.customer.consents?.whatsapp || 'UNKNOWN'}
              </span>
            </div>
          </div>
        </div>

        {/* Failed Attempt Context */}
        <div className="panel" style={{ padding: '16px 18px', background: '#ffffff' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--accent-danger-text)', fontWeight: 600, fontSize: '13px', marginBottom: '10px' }}>
            <CreditCard size={15} /> Failed Attempt Context
          </div>
          <div style={{ fontSize: '12.5px', display: 'flex', flexDirection: 'column', gap: '6px', color: 'var(--text-secondary)' }}>
            <div>Payment ID: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.payment_attempt?.payment_id || '—'}</span></div>
            <div>Method: <span className="mono" style={{ textTransform: 'uppercase', color: 'var(--text-primary)' }}>{detail.payment_attempt?.method || '—'}</span></div>
            <div>Error Code: <span className="mono" style={{ color: 'var(--accent-danger-text)', fontWeight: 600 }}>{detail.payment_attempt?.error_code || '—'}</span></div>
            <div>Reason: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.payment_attempt?.error_reason || '—'}</span></div>
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              Description: <em style={{ color: 'var(--text-primary)' }}>{detail.payment_attempt?.error_description || 'None'}</em>
            </div>
          </div>
        </div>

        {/* Decision Summary */}
        <div className="panel" style={{ padding: '16px 18px', background: '#ffffff' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--text-primary)', fontWeight: 600, fontSize: '13px', marginBottom: '10px' }}>
            <Zap size={15} color="var(--text-muted)" /> Decision Telemetry & Delivery
          </div>
          <div style={{ fontSize: '12.5px', display: 'flex', flexDirection: 'column', gap: '6px', color: 'var(--text-secondary)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>Policy Gate:</span>
              <span className={`badge ${detail.policy_evaluation?.decision_type === 'ELIGIBLE' ? 'badge-success' : 'badge-danger'}`}>
                {detail.policy_evaluation?.decision_type || '—'}
              </span>
            </div>
            <div>
              ROS Score:{' '}
              <strong style={{ color: (detail.decision_trace?.ros_score || 0) >= 65 ? 'var(--accent-success-text)' : 'var(--accent-warning-text)' }}>
                {detail.decision_trace?.ros_score ?? '—'}/100
              </strong>
            </div>
            <div>Diagnosis: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.decision_trace?.diagnosis_category || '—'}</span></div>
            <div>Action: <strong style={{ color: 'var(--text-primary)' }}>{detail.decision_trace?.selected_action || '—'}</strong></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>Delivery Mode:</span>
              <span className="badge badge-info">
                {detail.source === 'RAZORPAY_TEST_MODE' ? 'TERMINAL_ONLY' : 'LOCAL_SIMULATION'}
              </span>
            </div>
            <div>Contacts Sent: <strong style={{ color: 'var(--text-primary)' }}>{detail.source === 'RAZORPAY_TEST_MODE' ? 0 : detail.contact_count}</strong></div>
          </div>
        </div>
      </div>

      {/* Outreach & Reminder Controls Panel */}
      <div className="panel" style={{ marginBottom: '22px', background: '#ffffff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, fontSize: '14.5px', color: 'var(--text-primary)' }}>
              <Send size={15} color="var(--text-primary)" />
              Outreach & Reminder Controls
            </div>
            <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Dispatch an outreach reminder via approved Razorpay Payment Link Notification APIs.
            </div>
          </div>

          <div>
            <button
              className="btn btn-primary"
              disabled={detail.state === 'MANUAL_REVIEW'}
              onClick={() => {
                if (detail.state !== 'MANUAL_REVIEW') {
                  setShowReminderModal(true);
                  fetchPreview('sms');
                }
              }}
            >
              <Send size={13} />
              <span>Send reminder</span>
            </button>
          </div>
        </div>

        {/* MANUAL_REVIEW Blocking Reasons Banner */}
        {detail.state === 'MANUAL_REVIEW' && (
          <div
            style={{
              marginTop: '14px',
              padding: '12px 16px',
              background: 'var(--accent-danger-subtle)',
              border: '1px solid var(--accent-danger-border)',
              borderRadius: 'var(--radius-md)',
            }}
          >
            <div style={{ color: 'var(--accent-danger-text)', fontWeight: 600, fontSize: '13px', marginBottom: '4px' }}>
              Reminders disabled for MANUAL_REVIEW cases
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
              Outreach is blocked due to policy guardrails. Exact blocking reasons:
            </div>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              <span className="badge badge-danger" style={{ fontFamily: 'monospace' }}>
                CONTACT_CONSENT_MISSING
              </span>
              <span className="badge badge-danger" style={{ fontFamily: 'monospace' }}>
                INSUFFICIENT_CONTEXT
              </span>
              <span className="badge badge-danger" style={{ fontFamily: 'monospace' }}>
                PAYMENT_LINK_NOT_CREATED
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Reminder Confirmation Modal */}
      {showReminderModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '16px',
          }}
        >
          <div
            style={{
              background: '#ffffff',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
              maxWidth: '500px',
              width: '100%',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            <h2 style={{ margin: '0 0 8px 0', fontSize: '17px', color: 'var(--text-primary)', fontWeight: 600 }}>
              Confirm Reminder Dispatch
            </h2>
            <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginBottom: '18px' }}>
              Outreach reminders are sent via approved Razorpay Payment Link APIs. Please review the preview before confirmation.
            </div>

            {/* Medium Selector */}
            <div style={{ marginBottom: '14px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, display: 'block', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                Notification Channel
              </label>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  className={`btn ${reminderMedium === 'sms' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ flex: 1 }}
                  onClick={() => {
                    setReminderMedium('sms');
                    fetchPreview('sms');
                  }}
                >
                  SMS (WhatsApp)
                </button>
                <button
                  className={`btn ${reminderMedium === 'email' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ flex: 1 }}
                  onClick={() => {
                    setReminderMedium('email');
                    fetchPreview('email');
                  }}
                >
                  Email
                </button>
              </div>
            </div>

            {/* Preview Status & Metadata */}
            {previewLoading ? (
              <div style={{ padding: '20px', textAlign: 'center', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                <RefreshCw size={18} className="animate-spin" style={{ margin: '0 auto 8px auto', color: 'var(--text-primary)' }} />
                <div>Generating single-use confirmation token...</div>
              </div>
            ) : previewError ? (
              <div style={{ padding: '12px', background: 'var(--accent-danger-subtle)', border: '1px solid var(--accent-danger-border)', borderRadius: 'var(--radius-sm)', color: 'var(--accent-danger-text)', fontSize: '12.5px', marginBottom: '16px' }}>
                {previewError}
              </div>
            ) : previewData ? (
              <div
                style={{
                  background: '#f9fafb',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '12px 14px',
                  fontSize: '12px',
                  marginBottom: '18px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>Eligibility:</span>
                  <span className={`badge ${previewData.eligible ? 'badge-success' : 'badge-danger'}`}>
                    {previewData.eligible ? 'ELIGIBLE' : 'BLOCKED'}
                  </span>
                </div>

                {previewData.blocking_reasons?.length > 0 && (
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Blocking reasons: </span>
                    {previewData.blocking_reasons.map((r: string) => (
                      <span key={r} className="badge badge-danger" style={{ fontFamily: 'monospace', margin: '2px' }}>
                        {r}
                      </span>
                    ))}
                  </div>
                )}

                {previewData.masked_recipient && (
                  <div>Recipient: <span className="mono" style={{ color: 'var(--text-primary)' }}>{previewData.masked_recipient}</span></div>
                )}

                {previewData.provider_link_id && (
                  <div>Payment Link ID: <span className="mono" style={{ color: 'var(--text-primary)' }}>{previewData.provider_link_id}</span></div>
                )}

                {previewData.preview_token && (
                  <div>Token ID: <span className="mono" style={{ color: 'var(--accent-info-text)' }}>{previewData.preview_token.slice(0, 16)}...</span></div>
                )}
              </div>
            ) : null}

            {reminderSendError && (
              <div style={{ padding: '12px', background: 'var(--accent-danger-subtle)', border: '1px solid var(--accent-danger-border)', borderRadius: 'var(--radius-sm)', color: 'var(--accent-danger-text)', fontSize: '12px', marginBottom: '16px' }}>
                {reminderSendError}
              </div>
            )}

            {/* Modal Actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setShowReminderModal(false);
                  setPreviewData(null);
                  setReminderSendError(null);
                }}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                disabled={!previewData?.eligible || !previewData?.preview_token || sendingReminder}
                onClick={handleSendReminder}
              >
                {sendingReminder ? 'Sending...' : 'Confirm & Send Reminder'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '6px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '18px', overflowX: 'auto' }}>
        {[
          { id: 'timeline', label: 'Chronological Timeline', icon: Clock },
          { id: 'policy', label: 'Policy Gating', icon: Shield },
          { id: 'ros', label: 'ROS & Diagnosis', icon: Zap },
          { id: 'link', label: 'Payment Link & Messaging', icon: Send },
          { id: 'audit', label: 'Sanitized audit event timeline', icon: FileCode },
        ].map((t) => {
          const Icon = t.icon;
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id as any)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '7px',
                padding: '9px 14px',
                background: 'transparent',
                border: 'none',
                borderBottom: isActive ? '2px solid #111827' : '2px solid transparent',
                color: isActive ? '#111827' : 'var(--text-secondary)',
                fontWeight: isActive ? 600 : 500,
                fontSize: '13px',
                cursor: 'pointer',
                transition: 'all var(--transition-fast)',
                whiteSpace: 'nowrap',
              }}
            >
              <Icon size={14} color={isActive ? '#111827' : 'var(--text-muted)'} />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab 1: Chronological Timeline */}
      {activeTab === 'timeline' && (
        <div className="panel" style={{ background: '#ffffff' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 600, marginBottom: '16px', color: 'var(--text-primary)' }}>Case Lifecycle Progression</h3>
          <div className="timeline">
            {detail.timeline.map((evt) => (
              <div key={evt.step_number} className="timeline-item">
                <div className={`timeline-dot ${evt.status}`} />
                <div className="timeline-content">
                  <div className="timeline-header">
                    <div className="timeline-title">
                      #{evt.step_number} {evt.title}
                    </div>
                    <div className="timeline-time">{new Date(evt.timestamp).toLocaleTimeString()}</div>
                  </div>
                  <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                    {evt.description}
                  </div>
                  {Object.keys(evt.metadata).length > 0 && (
                    <pre
                      style={{
                        background: '#ffffff',
                        border: '1px solid var(--border-subtle)',
                        padding: '8px 10px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '11px',
                        color: 'var(--text-secondary)',
                        overflowX: 'auto',
                      }}
                    >
                      {JSON.stringify(evt.metadata, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 2: Policy Gating */}
      {activeTab === 'policy' && (
        <div className="panel" style={{ background: '#ffffff' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 600, marginBottom: '14px', color: 'var(--text-primary)' }}>Deterministic Policy Evaluation</h3>
          {detail.policy_evaluation ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                <div style={{ background: '#f9fafb', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Decision Result</div>
                  <div style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px' }}>
                    <span className={`badge ${detail.policy_evaluation.decision_type === 'ELIGIBLE' ? 'badge-success' : 'badge-danger'}`}>
                      {detail.policy_evaluation.decision_type}
                    </span>
                  </div>
                </div>
                <div style={{ background: '#f9fafb', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Policy Version</div>
                  <div className="mono" style={{ fontSize: '15px', fontWeight: 600, marginTop: '4px', color: 'var(--text-primary)' }}>
                    {detail.policy_evaluation.policy_version}
                  </div>
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: '12.5px', fontWeight: 600, marginBottom: '8px', color: 'var(--text-secondary)' }}>
                  Triggered Reason Codes
                </h4>
                {detail.policy_evaluation.reasons.length === 0 ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: '12.5px' }}>
                    None (Eligible for all recovery channels)
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {detail.policy_evaluation.reasons.map((r, i) => (
                      <span key={i} className="badge badge-danger">
                        {r}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Policy evaluation record not found.</div>
          )}
        </div>
      )}

      {/* Tab 3: ROS & Diagnosis */}
      {activeTab === 'ros' && (
        <div className="panel" style={{ background: '#ffffff' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 600, marginBottom: '14px', color: 'var(--text-primary)' }}>
            Recovery Opportunity Score (ROS) & Diagnosis Trace
          </h3>
          {detail.decision_trace ? (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '16px', marginBottom: '20px' }}>
                <div style={{ background: '#f9fafb', padding: '18px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', textAlign: 'center' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Composite ROS Score</div>
                  <div className="mono" style={{ fontSize: '38px', fontWeight: 800, color: 'var(--text-primary)', margin: '6px 0' }}>
                    {detail.decision_trace.ros_score}
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Scale: 0 to 100</div>
                </div>

                <div style={{ background: '#f9fafb', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '12.5px', fontWeight: 600, marginBottom: '10px', color: 'var(--text-secondary)' }}>
                    Feature Contributions Breakdown
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {Object.entries(detail.decision_trace.ros_contributions).map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>{k.replace(/_/g, ' ').toUpperCase()}</span>
                        <span className="mono" style={{ fontWeight: 700, color: (v as number) >= 0 ? 'var(--accent-success-text)' : 'var(--accent-danger-text)' }}>
                          {(v as number) >= 0 ? `+${v}` : v}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: '12.5px', fontWeight: 600, marginBottom: '8px', color: 'var(--text-secondary)' }}>
                  Candidate Action Simulation Utilities
                </h4>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {detail.decision_trace.action_candidates.map((act) => (
                    <div
                      key={act}
                      style={{
                        padding: '8px 12px',
                        background: act === detail.decision_trace?.selected_action ? '#f3f4f6' : '#ffffff',
                        border: act === detail.decision_trace?.selected_action ? '1px solid #111827' : '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        fontSize: '12px',
                      }}
                    >
                      <div style={{ fontWeight: 600, color: act === detail.decision_trace?.selected_action ? '#111827' : 'inherit' }}>
                        {act}
                      </div>
                      {act === detail.decision_trace?.selected_action && (
                        <div style={{ fontSize: '10px', color: 'var(--accent-success-text)', marginTop: '2px' }}>★ Selected Action</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Decision trace not recorded for this case.</div>
          )}
        </div>
      )}

      {/* Tab 4: Payment Link & Messaging */}
      {activeTab === 'link' && (
        <div className="panel" style={{ background: '#ffffff' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 600, marginBottom: '14px', color: 'var(--text-primary)' }}>
            Attributable Payment Link & Simulated Outreach
          </h3>
          {detail.payment_link ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ background: '#f9fafb', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <div style={{ fontWeight: 600, fontSize: '13.5px', display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--text-primary)' }}>
                    <Link size={15} color="var(--text-primary)" />
                    Payment Link Metadata
                  </div>
                  <span className={`badge ${detail.payment_link.status === 'paid' ? 'badge-success' : 'badge-info'}`}>
                    {detail.payment_link.status}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
                  <div>Provider Link ID: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.payment_link.provider_link_id}</span></div>
                  <div>Reference ID: <span className="mono" style={{ color: 'var(--text-primary)' }}>{detail.payment_link.reference_id}</span></div>
                  <div>Short URL: <a href={detail.payment_link.short_url} target="_blank" rel="noreferrer" style={{ color: 'var(--text-primary)', textDecoration: 'underline' }}>{detail.payment_link.short_url}</a></div>
                  <div>Expires By: <span className="mono" style={{ color: 'var(--text-primary)' }}>{new Date(detail.payment_link.expire_by).toLocaleString()}</span></div>
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: '12.5px', fontWeight: 600, marginBottom: '10px', color: 'var(--text-secondary)' }}>
                  Simulated Notification Dispatches
                </h4>
                {detail.notifications.length === 0 ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: '12.5px' }}>No notifications dispatched.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {detail.notifications.map((n) => (
                      <div key={n.notification_id} style={{ background: '#f9fafb', padding: '12px 14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', fontSize: '12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Channel: {n.channel}</span>
                          <span className="mono" style={{ color: 'var(--text-muted)' }}>{new Date(n.simulated_at).toLocaleTimeString()}</span>
                        </div>
                        <div>Recipient: <span className="mono" style={{ color: 'var(--text-primary)' }}>{n.masked_recipient}</span></div>
                        <div>Template: <span className="mono" style={{ color: 'var(--text-primary)' }}>{n.template_key}</span></div>
                        <div style={{ marginTop: '2px' }}>Status: <span className="badge badge-success">{n.status}</span></div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>No Payment Link created for this case.</div>
          )}
        </div>
      )}

      {/* Tab 5: Sanitized audit event timeline */}
      {activeTab === 'audit' && (
        <div className="panel" style={{ background: '#ffffff' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 600, marginBottom: '14px', color: 'var(--text-primary)' }}>
            Sanitized audit event timeline
          </h3>
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Event Type</th>
                  <th>Actor</th>
                  <th>State Before</th>
                  <th>State After</th>
                  <th>Metadata</th>
                </tr>
              </thead>
              <tbody>
                {detail.audit_events.map((a) => (
                  <tr key={a.event_id}>
                    <td className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                      {new Date(a.timestamp).toLocaleTimeString()}
                    </td>
                    <td>
                      <span className="badge badge-neutral">{a.event_type}</span>
                    </td>
                    <td style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{a.actor_type}</td>
                    <td className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{a.before_state || '—'}</td>
                    <td className="mono" style={{ fontSize: '11.5px', color: 'var(--text-primary)', fontWeight: 600 }}>{a.after_state || '—'}</td>
                    <td>
                      <pre style={{ fontSize: '10.5px', color: 'var(--text-secondary)', maxHeight: '60px', overflowY: 'auto' }}>
                        {JSON.stringify(a.sanitized_metadata)}
                      </pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
