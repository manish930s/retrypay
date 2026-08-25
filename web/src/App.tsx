import React, { useState } from 'react';
import { CheckCircle2, ShieldCheck } from 'lucide-react';
import { api } from './api';
import { Sidebar } from './components/Sidebar';
import { CaseDetailPage } from './pages/CaseDetailPage';
import { CaseListPage } from './pages/CaseListPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { OverviewPage } from './pages/OverviewPage';
import { SettingsPage } from './pages/SettingsPage';
import { SimulatorPage } from './pages/SimulatorPage';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<string>('overview');
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [isResetting, setIsResetting] = useState<boolean>(false);
  const [notification, setNotification] = useState<string | null>(null);

  const handleSelectTab = (tab: string) => {
    setSelectedCaseId(null);
    setCurrentTab(tab);
  };

  const handleSelectCase = (caseId: string) => {
    setSelectedCaseId(caseId);
  };

  const handleBackToCases = () => {
    setSelectedCaseId(null);
    setCurrentTab('cases');
  };

  const handleResetDemo = async () => {
    try {
      setIsResetting(true);
      await api.resetDemoDatabase();
      setNotification('Demo database successfully reset to clean seeded state.');
      setTimeout(() => setNotification(null), 4000);
      setSelectedCaseId(null);
    } catch (err: any) {
      alert(`Reset failed: ${err.message}`);
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        currentTab={selectedCaseId ? 'cases' : currentTab}
        onSelectTab={handleSelectTab}
        onResetDemo={handleResetDemo}
        isResetting={isResetting}
      />

      <main className="main-content">
        {/* Top Environment & Security Banner */}
        <header className="top-banner">
          <div className="banner-left">
            <ShieldCheck size={16} color="var(--accent-success-text)" />
            <span>Local demo operator console — not production authenticated.</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="env-tag">TEST MODE</span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              v1.3
            </span>
          </div>
        </header>

        {/* Global Alert Notification */}
        {notification && (
          <div
            style={{
              background: 'var(--accent-success-subtle)',
              border: '1px solid var(--accent-success-border)',
              borderRadius: 'var(--radius-md)',
              padding: '10px 16px',
              marginBottom: '20px',
              color: 'var(--accent-success-text)',
              fontSize: '13px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <CheckCircle2 size={16} />
            {notification}
          </div>
        )}

        {/* Dynamic Route Rendering */}
        {selectedCaseId ? (
          <CaseDetailPage caseId={selectedCaseId} onBack={handleBackToCases} />
        ) : (
          <>
            {currentTab === 'overview' && <OverviewPage onSelectCase={handleSelectCase} />}
            {currentTab === 'cases' && <CaseListPage onSelectCase={handleSelectCase} />}
            {currentTab === 'evaluation' && <EvaluationPage />}
            {currentTab === 'simulator' && <SimulatorPage onSelectCase={handleSelectCase} />}
            {currentTab === 'settings' && <SettingsPage />}
          </>
        )}
      </main>
    </div>
  );
};

export default App;
