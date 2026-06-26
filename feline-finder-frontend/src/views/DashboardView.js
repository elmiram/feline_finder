import React from 'react';
import {Play, Square} from 'lucide-react';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorDisplay from '../components/ErrorDisplay';
import StatusCard from '../components/StatusCard';
import EventLog from '../components/EventLog';

const DashboardView = ({catsStatus, statusLoading, statusError, lastRefreshTime, autoRefresh, setAutoRefresh}) => {
    return (
        <div>
            <div className="flex justify-center items-center space-x-4 mb-8">
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
                <div className={`grid grid-cols-1 gap-8 ${Object.values(catsStatus).length >= 3 ? 'lg:grid-cols-2 xl:grid-cols-3' : Object.values(catsStatus).length === 2 ? 'lg:grid-cols-2' : ''}`}>
                    {Object.values(catsStatus).map(cat => (
                        <div key={cat.name} className="flex flex-col gap-8">
                            <StatusCard cat={cat} lastRefresh={lastRefreshTime}/>
                            <div className="bg-white rounded-2xl shadow-lg p-6">
                                <EventLog events={cat.recent_events}/>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default DashboardView;