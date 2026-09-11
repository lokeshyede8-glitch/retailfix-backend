import os, textwrap

path = r'e:\Quotation\frontend\src\views\LeadManagement.jsx'

content = textwrap.dedent("""\
import { useState, useEffect } from 'react';
import { getLeads, getLeadStats, updateLead, deleteLead, createCustomer, getSalesmen, createSalesman, updateSalesman, deleteSalesman } from '../api';
import { useToast } from '../components/Toast';

const STATUS_COLORS = {
  'New Lead': '#3b82f6',
  'Contacted': '#f59e0b',
  'Visited': '#8b5cf6',
  'Converted': '#10b981',
  'Lost': '#ef4444'
};
const STATUSES = ['New Lead', 'Contacted', 'Visited', 'Converted', 'Lost'];
const TODAY = new Date().toISOString().slice(0, 10);

function fmtTs(ts) {
  return ts ? new Date(ts).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '-';
}

export default function LeadManagement() {
  const { showToast } = useToast();
  const [tab, setTab] = useState('leads');
  const [leads, setLeads] = useState([]);
  const [stats, setStats] = useState([]);
  const [salesmen, setSalesmen] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');

  // Salesman management
  const [showAddSalesman, setShowAddSalesman] = useState(false);
  const [smForm, setSmForm] = useState({ name: '', phone: '', pin: '', area: '' });
  const [smSaving, setSmSaving] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [l, st, sm] = await Promise.all([getLeads(), getLeadStats(), getSalesmen()]);
      setLeads(l);
      setStats(st);
      setSalesmen(sm);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleStatusChange = async (leadId, status) => {
    try {
      await updateLead(leadId, { status });
      setLeads(p => p.map(l => l.id === leadId ? { ...l, status } : l));
      showToast('Status updated successfully', 'ok');
      // Refresh stats in background
      getLeadStats().then(st => setStats(st)).catch(() => {});
    } catch {
      showToast('Failed to update status', 'err');
    }
  };

  const handleConvert = async (lead) => {
    if (!window.confirm('Convert ' + lead.customer_name + ' to Customer? This lead data will be copied to the Customer database.')) return;
    try {
      await createCustomer({
        name: lead.customer_name,
        phone: lead.phone,
        city: lead.city,
        address: lead.address
      });
      await updateLead(lead.id, { status: 'Converted' });
      setLeads(p => p.map(l => l.id === lead.id ? { ...l, status: 'Converted' } : l));
      showToast('Successfully converted to Customer!', 'ok');
      loadAll();
    } catch {
      showToast('Conversion failed', 'err');
    }
  };

  const handleDelete = async (leadId) => {
    if (!window.confirm('Are you sure you want to delete this lead?')) return;
    try {
      await deleteLead(leadId);
      setLeads(p => p.filter(l => l.id !== leadId));
      showToast('Lead deleted', 'ok');
      loadAll();
    } catch {
      showToast('Delete failed', 'err');
    }
  };

  const handleAddSalesman = async (e) => {
    e.preventDefault();
    if (!smForm.name.trim() || !smForm.pin.trim()) {
      showToast('Name and PIN required', 'err');
      return;
    }
    setSmSaving(true);
    try {
      await createSalesman(smForm);
      showToast('Salesman added successfully!', 'ok');
      setSmForm({ name: '', phone: '', pin: '', area: '' });
      setShowAddSalesman(false);
      loadAll();
    } catch (err) {
      showToast(err?.response?.data?.detail || 'Failed to add salesman', 'err');
    }
    setSmSaving(false);
  };

  const handleToggleSalesman = async (sm) => {
    try {
      await updateSalesman(sm.id, { active: !sm.active });
      showToast(sm.active ? 'Salesman deactivated' : 'Salesman activated', 'ok');
      loadAll();
    } catch {
      showToast('Failed to toggle salesman state', 'err');
    }
  };

  const handleDeleteSalesman = async (sm) => {
    if (!window.confirm('Delete salesman ' + sm.name + '?')) return;
    try {
      await deleteSalesman(sm.id);
      showToast('Salesman deleted', 'ok');
      loadAll();
    } catch {
      showToast('Failed to delete salesman', 'err');
    }
  };

  const filtered = leads.filter(l => {
    const q = search.toLowerCase();
    const matchSearch = !search ||
      l.customer_name.toLowerCase().includes(q) ||
      l.shop_name.toLowerCase().includes(q) ||
      l.city.toLowerCase().includes(q) ||
      l.lead_number.toLowerCase().includes(q);
    const matchStatus = statusFilter === 'All' || l.status === statusFilter;
    return matchSearch && matchStatus;
  });

  const followupLeads = leads.filter(l => l.follow_up_date && l.status !== 'Converted' && l.status !== 'Lost');
  const overdueFollowups = followupLeads.filter(l => l.follow_up_date < TODAY);
  const todayFollowups = followupLeads.filter(l => l.follow_up_date === TODAY);
  const upcomingFollowups = followupLeads.filter(l => l.follow_up_date > TODAY);

  // Statistics summaries
  const totalLeads = leads.length;
  const convertedLeads = leads.filter(l => l.status === 'Converted').length;
  const conversionRate = totalLeads ? Math.round((convertedLeads / totalLeads) * 100) : 0;
  const activeFollowups = followupLeads.length;

  return (
    <div className="lead-mgmt-wrap">
      {/* Title Header */}
      <div className="rf-section-head" style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span className="eyebrow">Enterprise CRM</span>
          <h1 style={{ margin: 0 }}>Lead Management</h1>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          {tab === 'salesmen' && (
            <button className="btn btn-primary" onClick={() => setShowAddSalesman(s => !s)}>
              {showAddSalesman ? 'Cancel' : '➕ Add Salesman'}
            </button>
          )}
        </div>
      </div>

      {/* KPI Stats Widgets Bar */}
      <div className="sales-stats-row" style={{ marginBottom: 24 }}>
        <div className="sales-stat-card" style={{ borderTop: '4px solid #6366f1' }}>
          <div className="sales-stat-num" style={{ color: '#1e1b4b' }}>{totalLeads}</div>
          <div className="sales-stat-label">Total Leads</div>
        </div>
        <div className="sales-stat-card" style={{ borderTop: '4px solid #10b981' }}>
          <div className="sales-stat-num" style={{ color: '#064e3b' }}>{convertedLeads}</div>
          <div className="sales-stat-label">Converted</div>
        </div>
        <div className="sales-stat-card" style={{ borderTop: '4px solid #8b5cf6' }}>
          <div className="sales-stat-num" style={{ color: '#4c1d95' }}>{conversionRate}%</div>
          <div className="sales-stat-label">Avg Conversion</div>
        </div>
        <div className="sales-stat-card" style={{ borderTop: '4px solid #f59e0b' }}>
          <div className="sales-stat-num" style={{ color: '#78350f' }}>{activeFollowups}</div>
          <div className="sales-stat-label">Active Followups</div>
        </div>
      </div>

      {/* Nav Tabs */}
      <div className="lead-mgmt-tabs" style={{ borderBottom: '1px solid var(--border)', marginBottom: 24 }}>
        {[
          ['leads', '🎯 Leads Directory'],
          ['performance', '📈 Sales Performance'],
          ['followups', '⏰ Follow-ups Planner'],
          ['salesmen', '👥 Salesmen Accounts']
        ].map(([k, label]) => (
          <button key={k} className={'tab-btn ' + (tab === k ? 'active' : '')} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="spinner-wrap"><div className="spinner" /></div>
      ) : (
        <div className="tab-content-panel">
          {/* Leads tab */}
          {tab === 'leads' && (
            <div>
              {/* Directory Filter Panel */}
              <div className="lead-mgmt-filters" style={{ background: '#faf9f6', padding: '16px 20px', borderRadius: 12, border: '1px solid var(--border)', marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
                <div style={{ display: 'flex', gap: 10, flex: 1, minWidth: 280 }}>
                  <div style={{ position: 'relative', width: '100%' }}>
                    <input
                      className="rf-input"
                      placeholder="Search name, shop, city, or ID..."
                      value={search}
                      onChange={e => setSearch(e.target.value)}
                      style={{ paddingLeft: 32 }}
                    />
                    <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#999' }}>🔍</span>
                  </div>
                </div>
                
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: '#666', fontWeight: 600, marginRight: 4 }}>Filter Status:</span>
                  <button className={'btn btn-sm ' + (statusFilter === 'All' ? 'btn-primary' : 'btn-ghost')} onClick={() => setStatusFilter('All')}>All</button>
                  {STATUSES.map(s => (
                    <button
                      key={s}
                      className={'btn btn-sm ' + (statusFilter === s ? 'btn-primary' : 'btn-ghost')}
                      onClick={() => setStatusFilter(s)}
                      style={{ color: statusFilter === s ? '#fff' : STATUS_COLORS[s] }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>

              {/* Grid Table */}
              <div className="rf-table-wrap" style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
                <table className="rf-table">
                  <thead>
                    <tr style={{ background: '#f5f4f0' }}>
                      <th style={{ padding: 14 }}>Lead No.</th>
                      <th>Customer Details</th>
                      <th>Shop Details</th>
                      <th>Location / City</th>
                      <th>Contact No.</th>
                      <th>Salesman</th>
                      <th>Status Badge</th>
                      <th>Follow-up</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 ? (
                      <tr>
                        <td colSpan={9} style={{ textAlign: 'center', padding: '48px 16px', color: '#999' }}>
                          <div style={{ fontSize: 32, marginBottom: 8 }}>🎯</div>
                          <strong>No leads found matches your filters.</strong>
                          <p style={{ margin: '4px 0 0', fontSize: 13 }}>Leads recorded by salesmen will appear here.</p>
                        </td>
                      </tr>
                    ) : (
                      filtered.map(l => (
                        <tr key={l.id} className="lead-row-hover" style={{ borderBottom: '1px solid #f0efeb' }}>
                          <td style={{ fontWeight: 'bold', color: '#4f46e5', padding: 14 }}>{l.lead_number}</td>
                          <td>
                            <div style={{ fontWeight: 600 }}>{l.customer_name}</div>
                            <div style={{ fontSize: 11, color: '#999' }}>Added: {fmtTs(l.created_at)}</div>
                          </td>
                          <td>
                            <div style={{ fontWeight: 500 }}>{l.shop_name}</div>
                            <div style={{ fontSize: 11, color: '#666' }}>{l.business_type || 'General Business'}</div>
                          </td>
                          <td>
                            <div>{l.city}</div>
                            <div style={{ fontSize: 11, color: '#999', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 160 }} title={l.address}>{l.address}</div>
                          </td>
                          <td>
                            <div style={{ fontFamily: 'monospace' }}>{l.phone}</div>
                          </td>
                          <td>
                            <span style={{ fontSize: 13, fontWeight: 500, color: '#4b5563' }}>👤 {l.salesman_name}</span>
                          </td>
                          <td>
                            <select
                              value={l.status}
                              onChange={e => handleStatusChange(l.id, e.target.value)}
                              className="rf-input"
                              style={{
                                padding: '4px 8px',
                                fontSize: 12,
                                fontWeight: 700,
                                border: '1px solid ' + STATUS_COLORS[l.status] + '77',
                                color: STATUS_COLORS[l.status],
                                background: STATUS_COLORS[l.status] + '11',
                                borderRadius: 8,
                                cursor: 'pointer',
                                outline: 'none'
                              }}
                            >
                              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                            </select>
                          </td>
                          <td style={{ color: l.follow_up_date && l.follow_up_date < TODAY ? '#ef4444' : '#6b7280', fontWeight: l.follow_up_date ? 600 : 400 }}>
                            {l.follow_up_date ? '📅 ' + l.follow_up_date : '-'}
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                              {l.status !== 'Converted' ? (
                                <button
                                  className="btn btn-sm"
                                  style={{ background: '#10b981', color: '#fff', border: 'none', fontWeight: 600, borderRadius: 6, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                                  onClick={() => handleConvert(l)}
                                  title="Approve and convert to active Customer"
                                >
                                  🔄 Convert
                                </button>
                              ) : (
                                <span style={{ fontSize: 11, color: '#10b981', fontWeight: 'bold', display: 'inline-flex', alignItems: 'center', gap: 3, padding: '4px 8px', background: '#d1fae5', borderRadius: 6 }}>
                                  ✓ Customer
                                </span>
                              )}
                              {l.latitude && (
                                <a
                                  href={'https://maps.google.com/?q=' + l.latitude + ',' + l.longitude}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="btn btn-sm btn-ghost"
                                  style={{ borderRadius: 6 }}
                                  title="View GPS Captured Location"
                                >
                                  📍 Map
                                </a>
                              )}
                              <button
                                className="btn btn-sm btn-ghost"
                                style={{ color: '#ef4444', borderRadius: 6 }}
                                onClick={() => handleDelete(l.id)}
                                title="Delete Lead permanently"
                              >
                                🗑
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Performance tab */}
          {tab === 'performance' && (
            <div>
              <div className="sales-perf-grid">
                {stats.length === 0 ? (
                  <div className="empty-state" style={{ gridColumn: '1/-1' }}>
                    <h3>No Performance Data yet</h3>
                    <p>Leads performance statistics will be plotted once leads are captured by the salesmen.</p>
                  </div>
                ) : (
                  stats.map(s => (
                    <div key={s.salesman_id} className="sales-perf-card" style={{ background: '#fff', padding: 24, borderRadius: 16, border: '1px solid var(--border)', boxShadow: '0 2px 10px rgba(0,0,0,0.05)' }}>
                      <div className="sales-perf-name" style={{ fontSize: 18, fontWeight: 700, color: '#1e1b4b', marginBottom: 16, borderBottom: '1px solid #f0f0f0', paddingBottom: 8 }}>
                        👤 {s.salesman_name}
                      </div>
                      <div className="sales-perf-stats" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
                        <div style={{ textAlign: 'center', flex: 1 }}>
                          <div style={{ fontSize: 24, fontWeight: 800, color: '#3b82f6' }}>{s.total_leads}</div>
                          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>Leads Taken</div>
                        </div>
                        <div style={{ textAlign: 'center', flex: 1, borderLeft: '1px solid #f0f0f0', borderRight: '1px solid #f0f0f0' }}>
                          <div style={{ fontSize: 24, fontWeight: 800, color: '#10b981' }}>{s.converted}</div>
                          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>Converted</div>
                        </div>
                        <div style={{ textAlign: 'center', flex: 1 }}>
                          <div style={{ fontSize: 24, fontWeight: 800, color: '#8b5cf6' }}>{s.conversion_rate}%</div>
                          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>Rate</div>
                        </div>
                      </div>
                      <div className="progress-bar-container">
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#666', marginBottom: 4, fontWeight: 500 }}>
                          <span>Conversion Progress</span>
                          <span>{s.conversion_rate}%</span>
                        </div>
                        <div className="sales-perf-bar-wrap" style={{ background: '#f3f4f6', height: 8, borderRadius: 4, overflow: 'hidden' }}>
                          <div className="sales-perf-bar" style={{ width: s.conversion_rate + '%', height: '100%', background: 'linear-gradient(90deg, #3b82f6, #10b981)', borderRadius: 4 }} />
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* Followups Planner tab */}
          {tab === 'followups' && (
            <div className="followup-sections" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 20 }}>
              {/* Overdue column */}
              <div style={{ background: '#fff1f2', padding: 18, borderRadius: 16, border: '1px solid #ffe4e6' }}>
                <h3 style={{ color: '#be123c', margin: '0 0 16px 0', borderBottom: '1px solid #fecdd3', paddingBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                  <span>⚠️ Overdue</span>
                  <span style={{ background: '#fecdd3', fontSize: 12, padding: '2px 8px', borderRadius: 12, color: '#be123c' }}>{overdueFollowups.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: '60vh', overflowY: 'auto', paddingRight: 4 }}>
                  {overdueFollowups.length === 0 ? (
                    <div style={{ color: '#9f1239', fontSize: 13, textAlign: 'center', padding: '16px 0' }}>No overdue follow-ups. Good job!</div>
                  ) : (
                    overdueFollowups.map(l => <FollowupCard key={l.id} lead={l} onStatusChange={handleStatusChange} />)
                  )}
                </div>
              </div>

              {/* Today column */}
              <div style={{ background: '#fffbeb', padding: 18, borderRadius: 16, border: '1px solid #fef3c7' }}>
                <h3 style={{ color: '#b45309', margin: '0 0 16px 0', borderBottom: '1px solid #fde68a', paddingBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                  <span>⏰ Today's Action</span>
                  <span style={{ background: '#fde68a', fontSize: 12, padding: '2px 8px', borderRadius: 12, color: '#b45309' }}>{todayFollowups.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: '60vh', overflowY: 'auto', paddingRight: 4 }}>
                  {todayFollowups.length === 0 ? (
                    <div style={{ color: '#92400e', fontSize: 13, textAlign: 'center', padding: '16px 0' }}>No follow-ups due today.</div>
                  ) : (
                    todayFollowups.map(l => <FollowupCard key={l.id} lead={l} onStatusChange={handleStatusChange} />)
                  )}
                </div>
              </div>

              {/* Upcoming column */}
              <div style={{ background: '#eff6ff', padding: 18, borderRadius: 16, border: '1px solid #dbeafe' }}>
                <h3 style={{ color: '#1d4ed8', margin: '0 0 16px 0', borderBottom: '1px solid #bfdbfe', paddingBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                  <span>📅 Upcoming</span>
                  <span style={{ background: '#bfdbfe', fontSize: 12, padding: '2px 8px', borderRadius: 12, color: '#1d4ed8' }}>{upcomingFollowups.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: '60vh', overflowY: 'auto', paddingRight: 4 }}>
                  {upcomingFollowups.length === 0 ? (
                    <div style={{ color: '#1e40af', fontSize: 13, textAlign: 'center', padding: '16px 0' }}>No upcoming follow-ups scheduled.</div>
                  ) : (
                    upcomingFollowups.map(l => <FollowupCard key={l.id} lead={l} onStatusChange={handleStatusChange} />)
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Salesmen Accounts tab */}
          {tab === 'salesmen' && (
            <div>
              {showAddSalesman && (
                <form onSubmit={handleAddSalesman} className="salesman-add-form" style={{ background: '#fafafa', border: '1px solid var(--border)', borderRadius: 16, padding: 24, marginBottom: 24 }}>
                  <h3 style={{ margin: '0 0 16px 0', borderBottom: '1px solid #f0f0f0', paddingBottom: 8 }}>Add New Salesman Portal Account</h3>
                  <div className="lead-form-grid" style={{ marginBottom: 12 }}>
                    <div className="rf-field"><label>Salesman Name *</label><input className="rf-input" value={smForm.name} onChange={e => setSmForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Rahul Sharma" required /></div>
                    <div className="rf-field"><label>Mobile Number</label><input className="rf-input" value={smForm.phone} onChange={e => setSmForm(f => ({ ...f, phone: e.target.value }))} placeholder="10-digit number" /></div>
                  </div>
                  <div className="lead-form-grid" style={{ marginBottom: 20 }}>
                    <div className="rf-field"><label>Login PIN * (4-6 digits)</label><input className="rf-input" type="password" value={smForm.pin} onChange={e => setSmForm(f => ({ ...f, pin: e.target.value }))} placeholder="Numeric PIN" maxLength={6} required /></div>
                    <div className="rf-field"><label>Assigned Territory / Area</label><input className="rf-input" value={smForm.area} onChange={e => setSmForm(f => ({ ...f, area: e.target.value }))} placeholder="e.g. Bhopal Zone-1" /></div>
                  </div>
                  <div style={{ display: 'flex', gap: 10 }}>
                    <button type="submit" className="btn btn-primary" disabled={smSaving}>{smSaving ? 'Saving Account...' : '💾 Save Account'}</button>
                    <button type="button" className="btn btn-ghost" onClick={() => setShowAddSalesman(false)}>Dismiss</button>
                  </div>
                </form>
              )}

              <div className="rf-table-wrap" style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
                <table className="rf-table">
                  <thead>
                    <tr style={{ background: '#f5f4f0' }}>
                      <th style={{ padding: 14 }}>Name</th>
                      <th>Contact No.</th>
                      <th>Territory / Area</th>
                      <th>Terminal PIN</th>
                      <th>Total Leads</th>
                      <th>Portal Access</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {salesmen.length === 0 ? (
                      <tr><td colSpan={7} style={{ textAlign: 'center', padding: '32px 16px', color: '#999' }}>No salesmen portal accounts configured.</td></tr>
                    ) : (
                      salesmen.map(sm => (
                        <tr key={sm.id} style={{ borderBottom: '1px solid #f0efeb' }}>
                          <td style={{ fontWeight: 'bold', padding: 14 }}>👤 {sm.name}</td>
                          <td>{sm.phone || 'N/A'}</td>
                          <td><span style={{ fontWeight: 500, color: '#6b7280' }}>📍 {sm.area || 'All Areas'}</span></td>
                          <td style={{ letterSpacing: 3, fontFamily: 'monospace', fontSize: 14 }}>••••</td>
                          <td style={{ fontWeight: 600 }}>{sm.lead_count} leads</td>
                          <td>
                            <span className="status-badge" style={{ background: sm.active ? '#d1fae5' : '#fee2e2', color: sm.active ? '#047857' : '#b91c1c', border: '1px solid ' + (sm.active ? '#a7f3d0' : '#fecaca') }}>
                              {sm.active ? '🟢 Authorized' : '🔴 Blocked'}
                            </span>
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                              <button
                                className={'btn btn-sm ' + (sm.active ? 'btn-ghost' : 'btn-primary')}
                                style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6 }}
                                onClick={() => handleToggleSalesman(sm)}
                              >
                                {sm.active ? '🔒 Block Portal' : '🔓 Authorize'}
                              </button>
                              <button
                                className="btn btn-sm btn-ghost"
                                style={{ color: '#ef4444', borderRadius: 6 }}
                                onClick={() => handleDeleteSalesman(sm)}
                              >
                                🗑 Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FollowupCard({ lead, onStatusChange }) {
  return (
    <div className="followup-card" style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 12, padding: 14, boxShadow: '0 1px 4px rgba(0,0,0,0.03)' }}>
      <div className="followup-card-top" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#111827' }}>{lead.customer_name}</div>
          <div style={{ fontSize: 12, color: '#4b5563', fontWeight: 500, marginTop: 2 }}>🏪 {lead.shop_name}</div>
          <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 1 }}>👤 {lead.salesman_name} | 📍 {lead.city}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignSelf: 'stretch', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <span className="status-badge" style={{ background: STATUS_COLORS[lead.status] + '15', color: STATUS_COLORS[lead.status], border: '1px solid ' + STATUS_COLORS[lead.status] + '33', fontSize: 10, padding: '2px 6px', borderRadius: 6 }}>
            {lead.status}
          </span>
          <span style={{ fontSize: 11, color: '#6b7280', marginTop: 4, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            📅 <strong>{lead.follow_up_date}</strong>
          </span>
        </div>
      </div>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 10, borderTop: '1px dashed #f0f0f0' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          {lead.phone && (
            <>
              <a href={'tel:' + lead.phone} className="btn btn-sm btn-ghost" style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                📞 Call
              </a>
              <a
                href={'https://wa.me/91' + lead.phone.replace(/[^0-9]/g, '')}
                target="_blank"
                rel="noreferrer"
                className="btn btn-sm"
                style={{ background: '#25d366', color: '#fff', border: 'none', fontSize: 11, padding: '4px 10px', borderRadius: 6, display: 'inline-flex', alignItems: 'center', gap: 3 }}
              >
                💬 WhatsApp
              </a>
            </>
          )}
        </div>
        <div>
          <select
            value={lead.status}
            onChange={e => onStatusChange(lead.id, e.target.value)}
            className="rf-input"
            style={{
              padding: '3px 6px',
              fontSize: 11,
              fontWeight: 600,
              border: '1px solid #d1d5db',
              borderRadius: 6,
              background: '#f9fafb',
              color: '#374151',
              cursor: 'pointer',
              outline: 'none'
            }}
          >
            {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>
    </div>
  );
}
""")

with open(path, 'w', encoding='utf-8') as f:
  f.write(content)

print("LeadManagement.jsx successfully overwritten")






