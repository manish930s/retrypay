import React, { useEffect, useState } from 'react';
import { Bot, CheckCircle2, Lock, RefreshCw, Shield, Sliders } from 'lucide-react';
import { api } from '../api';
import { SettingsData } from '../types';

export const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const data = await api.getSettings();
      setSettings(data);
    } catch (err) {
      console.error('Failed to load settings:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
        <RefreshCw size={22} className="animate-spin" style={{ margin: '0 auto 12px auto', color: 'var(--text-primary)' }} />
        <div style={{ fontSize: '13.5px', fontWeight: 500 }}>Loading settings snapshot...</div>
      </div>
    );
  }

  if (!settings) return null;

  return (
    <div>
      {/* Page Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 className="page-title">Policy & Operational Guardrails</h1>
          <p className="page-subtitle">Read-only merchant configuration, safety thresholds, and scoring versions.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span className="badge badge-neutral" style={{ padding: '4px 10px', fontSize: '11px', textTransform: 'none', background: '#f3f4f6' }}>
            <CheckCircle2 size={13} color="var(--accent-success-text)" />
            Read-Only Policy Snapshot
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '20px' }}>
        {/* Policy Configuration Card */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <Shield size={16} color="var(--text-primary)" />
              Recovery Policy Configuration
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Environment</span>
              <span className="env-tag">{settings.environment.toUpperCase()}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Policy Version</span>
              <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{settings.policy_version}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Attribution Reconciliation Window</span>
              <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                {settings.attribution_reconciliation_window_minutes} Minutes
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Quiet Hours</span>
              <span style={{ color: 'var(--text-primary)' }}>
                {settings.quiet_hours.enabled
                  ? `${settings.quiet_hours.start_hour}:00 - ${settings.quiet_hours.end_hour}:00 (${settings.quiet_hours.timezone})`
                  : 'Disabled'}
              </span>
            </div>
          </div>
        </div>

        {/* Operational Guardrails */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <Lock size={16} color="var(--text-primary)" />
              Operational Guardrails & Caps
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Single Action GMV Limit</span>
              <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                ₹{(settings.guardrails.single_action_limit_paise / 100).toLocaleString('en-IN')}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Daily Merchant GMV Cap</span>
              <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                ₹{(settings.guardrails.daily_gmv_cap_paise / 100).toLocaleString('en-IN')}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Daily Action Cap</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.guardrails.daily_action_cap} Actions</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Daily Contact Cap</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.guardrails.daily_contact_cap} Contacts</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Max Manual Review Queue Depth</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.guardrails.max_manual_review_queue_depth} Cases</span>
            </div>
          </div>
        </div>

        {/* Scoring & Diagnosis Engines */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <Sliders size={16} color="var(--text-primary)" />
              Scoring & Mapper Versions
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Razorpay Error Mapper</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.mapper_version}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Recovery Opportunity Score (ROS)</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.ros_version}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Simulation Estimator</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.estimator_version}</span>
            </div>
          </div>
        </div>

        {/* LLM & AI Advisory Telemetry */}
        <div className="panel" style={{ background: '#ffffff' }}>
          <div className="panel-header">
            <h2 className="panel-title">
              <Bot size={16} color="var(--text-primary)" />
              LLM Advisory Configuration
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Gemini LLM Provider</span>
              <span className={`badge ${settings.llm_enabled ? 'badge-success' : 'badge-neutral'}`}>
                {settings.llm_enabled ? 'ENABLED' : 'DISABLED (Rules Default)'}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#f9fafb', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Model Name</span>
              <span className="mono" style={{ color: 'var(--text-primary)' }}>{settings.llm_model}</span>
            </div>
            <div
              style={{
                padding: '10px 14px',
                background: '#f9fafb',
                border: '1px dashed var(--border-medium)',
                borderRadius: 'var(--radius-md)',
                fontSize: '12px',
                color: 'var(--text-secondary)',
                lineHeight: 1.45,
              }}
            >
              <em>LLM output is restricted to diagnosis classification & explanation only. AI cannot authorize an action or override deterministic policy.</em>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
