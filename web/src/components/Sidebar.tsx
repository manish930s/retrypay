import React from 'react';
import {
  LayoutDashboard,
  ShieldAlert,
  BarChart3,
  Terminal,
  Sliders,
  RotateCcw,
  ShieldCheck,
  Zap,
} from 'lucide-react';

interface SidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  onResetDemo: () => void;
  isResetting: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onSelectTab,
  onResetDemo,
  isResetting,
}) => {
  const navItems = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard },
    { id: 'cases', label: 'Recovery Cases', icon: ShieldAlert },
    { id: 'evaluation', label: 'Causal Evaluation', icon: BarChart3 },
    { id: 'simulator', label: 'Webhook Simulator', icon: Terminal },
    { id: 'settings', label: 'Policy & Guardrails', icon: Sliders },
  ];

  return (
    <aside className="sidebar">
      {/* Brand Header */}
      <div className="brand">
        <div className="brand-icon">
          <Zap size={18} strokeWidth={2.5} />
        </div>
        <div>
          <div className="brand-name">ReTryPay</div>
          <span className="brand-badge">Operator Console</span>
        </div>
      </div>

      {/* Main Navigation Links */}
      <nav className="nav-links" aria-label="Main Navigation">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentTab === item.id;
          return (
            <button
              key={item.id}
              className={`nav-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelectTab(item.id)}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon size={16} strokeWidth={isActive ? 2.2 : 1.8} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Footer System Status & Reset Demo */}
      <div className="sidebar-footer">
        <button
          className="btn btn-secondary"
          style={{ width: '100%', fontSize: '12px', padding: '8px 12px' }}
          onClick={onResetDemo}
          disabled={isResetting}
          title="Reset test database state to clean seed"
        >
          <RotateCcw size={13} className={isResetting ? 'animate-spin' : ''} />
          <span>{isResetting ? 'Resetting...' : 'Reset Demo State'}</span>
        </button>

        <div
          style={{
            fontSize: '11px',
            color: 'var(--text-muted)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px',
            padding: '4px 0',
          }}
        >
          <ShieldCheck size={13} color="var(--accent-success-text)" />
          <span>Test Mode Isolated</span>
        </div>
      </div>
    </aside>
  );
};
