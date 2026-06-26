import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../constants';

function TrackerBadge({ tracker }) {
    return (
        <div className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm ${tracker.active ? 'bg-green-50 border border-green-200' : 'bg-gray-50 border border-gray-200'}`}>
            <div>
                <span className={`font-mono font-semibold ${tracker.active ? 'text-green-800' : 'text-gray-500'}`}>
                    {tracker.tracker_id}
                </span>
                <span className={`ml-2 text-xs ${tracker.active ? 'text-green-600' : 'text-gray-400'}`}>
                    {tracker.active ? 'Active' : `Retired ${tracker.retired_date ? tracker.retired_date.slice(0, 10) : ''}`}
                </span>
            </div>
            <span className={`text-xs ${tracker.active ? 'text-green-500' : 'text-gray-400'}`}>
                since {tracker.assigned_date ? tracker.assigned_date.slice(0, 10) : '?'}
            </span>
        </div>
    );
}

function CatTrackerCard({ catName, data, onAssign, onReactivate }) {
    const [newId, setNewId] = useState('');
    const [lostDate, setLostDate] = useState('');
    const [assigning, setAssigning] = useState(false);
    const [message, setMessage] = useState(null);
    const [reactivatingId, setReactivatingId] = useState(null);
    const [reactivateDates, setReactivateDates] = useState({});

    const retiredTrackers = data.trackers.filter(t => !t.active);

    const handleAssign = async (e) => {
        e.preventDefault();
        if (!newId.trim()) return;
        setAssigning(true);
        setMessage(null);
        try {
            await onAssign(catName, newId.trim().toUpperCase(), lostDate || null);
            setMessage({ type: 'success', text: 'Tracker assigned. Backfill running in background.' });
            setNewId('');
            setLostDate('');
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setAssigning(false);
        }
    };

    const handleReactivate = async (trackerId) => {
        setReactivatingId(trackerId);
        setMessage(null);
        try {
            await onReactivate(catName, trackerId, reactivateDates[trackerId] || null);
            setMessage({ type: 'success', text: `${trackerId} reactivated. Gap backfill running in background.` });
            setReactivateDates(d => ({ ...d, [trackerId]: '' }));
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setReactivatingId(null);
        }
    };

    return (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 space-y-4">
            <h3 className="text-lg font-bold text-gray-800">{catName}</h3>

            <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Tracker history</p>
                {data.trackers.length === 0
                    ? <p className="text-sm text-gray-400">No tracker records.</p>
                    : data.trackers.map(t => <TrackerBadge key={t.tracker_id + t.assigned_date} tracker={t} />)
                }
            </div>

            {retiredTrackers.length > 0 && (
                <div className="space-y-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Re-activate retired tracker</p>
                    {retiredTrackers.map(t => (
                        <div key={t.tracker_id} className="space-y-1">
                            <div className="flex items-center justify-between">
                                <span className="font-mono text-sm text-gray-500">{t.tracker_id}</span>
                                <button
                                    onClick={() => handleReactivate(t.tracker_id)}
                                    disabled={reactivatingId === t.tracker_id}
                                    className="text-xs px-3 py-1 rounded-lg bg-yellow-100 text-yellow-800 hover:bg-yellow-200 disabled:opacity-50 font-semibold transition-colors"
                                >
                                    {reactivatingId === t.tracker_id ? 'Saving…' : 'Re-activate'}
                                </button>
                            </div>
                            <input
                                type="date"
                                value={reactivateDates[t.tracker_id] || ''}
                                onChange={e => setReactivateDates(d => ({ ...d, [t.tracker_id]: e.target.value }))}
                                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-yellow-300"
                                title="Override gap start date (when tracker was actually lost)"
                            />
                            <p className="text-xs text-gray-400">Gap start date — leave blank to use the recorded retirement date</p>
                        </div>
                    ))}
                </div>
            )}

            <form onSubmit={handleAssign} className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Assign new tracker</p>
                <input
                    type="text"
                    value={newId}
                    onChange={e => setNewId(e.target.value)}
                    placeholder="New tracker ID (e.g. ABCD1234)"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
                <div className="space-y-1">
                    <input
                        type="date"
                        value={lostDate}
                        onChange={e => setLostDate(e.target.value)}
                        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-300"
                    />
                    <p className="text-xs text-gray-400">Date tracker was lost — sets backfill start (leave blank to fetch full history)</p>
                </div>
                <button
                    type="submit"
                    disabled={assigning || !newId.trim()}
                    className="w-full py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    {assigning ? 'Saving…' : 'Assign Tracker'}
                </button>
            </form>

            {message && (
                <p className={`text-sm rounded-lg px-3 py-2 ${message.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                    {message.text}
                </p>
            )}
        </div>
    );
}

export default function SettingsView() {
    const [trackerData, setTrackerData] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchTrackers = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_BASE_URL}/api/trackers`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            setTrackerData(await res.json());
        } catch (e) {
            setError('Could not load tracker data.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchTrackers(); }, []);

    const handleAssign = async (catName, trackerId, lostDate) => {
        const res = await fetch(`${API_BASE_URL}/api/trackers/assign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cat_name: catName, tracker_id: trackerId, lost_date: lostDate }),
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || `HTTP ${res.status}`);
        }
        await fetchTrackers();
    };

    const handleReactivate = async (catName, trackerId, lostDate) => {
        const res = await fetch(`${API_BASE_URL}/api/trackers/reactivate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cat_name: catName, tracker_id: trackerId, lost_date: lostDate }),
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || `HTTP ${res.status}`);
        }
        await fetchTrackers();
    };

    if (loading) return <p className="text-gray-500 text-center py-12">Loading tracker data…</p>;
    if (error) return <p className="text-red-500 text-center py-12">{error}</p>;

    return (
        <div className="space-y-6">
            <div>
                <h2 className="text-xl font-bold text-gray-700">Tracker Management</h2>
                <p className="text-sm text-gray-400 mt-1">
                    Assign a new tracker ID when a collar is replaced, or re-activate a recovered one.
                    Historical GPS data is fetched automatically in the background.
                </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                {Object.entries(trackerData).map(([catName, data]) => (
                    <CatTrackerCard
                        key={catName}
                        catName={catName}
                        data={data}
                        onAssign={handleAssign}
                        onReactivate={handleReactivate}
                    />
                ))}
            </div>
        </div>
    );
}
