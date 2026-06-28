import React, { useState, useEffect } from 'react';
import {Play, Square} from 'lucide-react';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorDisplay from '../components/ErrorDisplay';
import StatusCard from '../components/StatusCard';
import EventLog from '../components/EventLog';
import { API_BASE_URL } from '../constants';

const ACTIVE_CATS = ['Arthur', 'King'];

const formatRecordDate = (timestamp) => {
    if (!timestamp) return null;
    // timestamp is like "2025-04-25 08:43:33" (UTC)
    const d = new Date(timestamp.replace(' ', 'T') + 'Z');
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
};

const DashboardView = ({catsStatus, statusLoading, statusError, lastRefreshTime, autoRefresh, setAutoRefresh}) => {
    const catList = Object.values(catsStatus);
    const catCount = catList.length;

    const [records, setRecords] = useState({});

    useEffect(() => {
        ACTIVE_CATS.forEach(async (catName) => {
            try {
                const res = await fetch(`${API_BASE_URL}/api/stats/farthest?cat_name=${encodeURIComponent(catName)}`);
                if (!res.ok) return;
                const data = await res.json();
                if (data.distance_km !== null) {
                    setRecords(prev => ({ ...prev, [catName]: data }));
                }
            } catch (e) {
                // silently ignore — record card is optional
            }
        });
    }, []); // fetch once on mount

    return (
        <div>
            <div className="hidden sm:flex justify-center items-center space-x-4 mb-8">
                {autoRefresh ? (
                    <button onClick={() => setAutoRefresh(false)}
                            className="flex items-center space-x-2 px-4 py-2 bg-red-500 text-white rounded-lg shadow-md hover:bg-red-600 transition-colors">
                        <Square className="w-5 h-5"/><span>Stop Auto-Refresh</span></button>
                ) : (
                    <button onClick={() => setAutoRefresh(true)}
                            className="flex items-center space-x-2 px-4 py-2 bg-green-500 text-white rounded-lg shadow-md hover:bg-green-600 transition-colors">
                        <Play className="w-5 h-5"/><span>Start Auto-Refresh</span></button>
                )}
            </div>

            {statusLoading ? <LoadingSpinner/> : statusError ? <ErrorDisplay message={statusError}/> : (
                <>
                    {/* Mobile layout: status cards side by side, event logs stacked below */}
                    <div className="sm:hidden">
                        <div className={`grid gap-3 mb-3 ${catCount >= 2 ? 'grid-cols-2' : 'grid-cols-1'}`}>
                            {catList.map(cat => (
                                <div key={cat.name}
                                     style={cat.long_absence_flag ? { border: '2px solid #F59E0B', borderRadius: '0.75rem' } : {}}>
                                    <StatusCard cat={cat} lastRefresh={lastRefreshTime}/>
                                    {cat.long_absence_flag && (
                                        <p className="text-xs font-semibold px-3 pb-2" style={{ color: '#F59E0B' }}>
                                            ⚠ Outside longer than usual
                                        </p>
                                    )}
                                    {records[cat.name] && (
                                        <div className="mt-2 bg-white rounded-xl shadow px-3 py-2 text-xs text-gray-500">
                                            <span className="font-semibold text-gray-700">Record: </span>
                                            {records[cat.name].distance_km.toFixed(2)} km
                                            {formatRecordDate(records[cat.name].timestamp) && (
                                                <span> · {formatRecordDate(records[cat.name].timestamp)}</span>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                        <div className="grid grid-cols-1 gap-3">
                            {catList.map(cat => (
                                <div key={cat.name} className="bg-white rounded-2xl shadow-lg p-3">
                                    <p className="text-xs font-semibold text-gray-400 mb-1">{cat.name}</p>
                                    <EventLog events={cat.recent_events} zoneChanges={cat.recent_zone_changes}/>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Desktop layout: each cat's card and events in a paired column */}
                    <div className={`hidden sm:grid gap-8 ${catCount >= 3 ? 'lg:grid-cols-2 xl:grid-cols-3' : catCount === 2 ? 'lg:grid-cols-2' : ''}`}>
                        {catList.map(cat => (
                            <div key={cat.name} className="flex flex-col gap-8">
                                <div style={cat.long_absence_flag ? { border: '2px solid #F59E0B', borderRadius: '0.75rem' } : {}}>
                                    <StatusCard cat={cat} lastRefresh={lastRefreshTime}/>
                                    {cat.long_absence_flag && (
                                        <p className="text-sm font-semibold px-6 pb-3" style={{ color: '#F59E0B' }}>
                                            ⚠ Outside longer than usual
                                        </p>
                                    )}
                                    {records[cat.name] && (
                                        <div className="mt-3 bg-white rounded-xl shadow px-4 py-2 text-sm text-gray-500 flex items-center justify-between">
                                            <span className="font-semibold text-gray-700">Record distance from home</span>
                                            <span className="font-mono text-gray-800">
                                                {records[cat.name].distance_km.toFixed(2)} km
                                                {formatRecordDate(records[cat.name].timestamp) && (
                                                    <span className="font-sans font-normal text-gray-500 ml-1">· {formatRecordDate(records[cat.name].timestamp)}</span>
                                                )}
                                            </span>
                                        </div>
                                    )}
                                </div>
                                <div className="bg-white rounded-2xl shadow-lg p-6">
                                    <EventLog events={cat.recent_events} zoneChanges={cat.recent_zone_changes}/>
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
};

export default DashboardView;
