import React from 'react';
import {Home, TreeDeciduous, Battery, AlertTriangle, PawPrint, Satellite, DoorOpen, RefreshCw} from 'lucide-react';
import BatteryStatus from './BatteryStatus';
import {formatRelativeTime} from '../utils/time';

const StatusCard = ({cat, lastRefresh}) => {
    const getConfidenceColor = (c) => (c === 'High' ? 'bg-green-100 text-green-800' : c === 'Medium' ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800');

    const getStatusIcon = (s) => {
        const ls = s.toLowerCase();
        if (ls.includes('home')) return <Home className="w-6 h-6 text-blue-500"/>;
        if (ls.includes('outside')) return <TreeDeciduous className="w-6 h-6 text-green-500"/>;
        if (ls.includes('charging')) return <Battery className="w-6 h-6 text-yellow-500"/>;
        return <AlertTriangle className="w-6 h-6 text-gray-500"/>;
    };

    return (
        <div
            className="bg-white rounded-2xl shadow-lg p-6 flex flex-col justify-between transform hover:scale-105 transition-transform duration-300">
            <div>
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-3">
                        <div className="bg-gray-100 p-3 rounded-full"><PawPrint className="w-6 h-6 text-gray-600"/>
                        </div>
                        <h2 className="text-2xl font-bold text-gray-800">{cat.name}</h2>
                    </div>
                    <BatteryStatus level={cat.battery_level} isCharging={cat.is_charging}/>
                </div>
                <div className="flex items-start space-x-3 my-4">
                    {getStatusIcon(cat.status)}
                    <div>
                        <p className="text-xl font-semibold text-gray-700">{cat.status}</p>
                        {cat.location_detail && (
                            <p className="text-sm text-blue-600 font-medium">{cat.location_detail}</p>
                        )}
                    </div>
                </div>
                <p className="text-gray-500 text-sm mb-4 h-10">{cat.evidence}</p>
            </div>
            <div className="border-t pt-4 mt-4">
                <div className="flex justify-between items-center mb-3">
                    <span
                        className={`px-3 py-1 text-sm font-semibold rounded-full ${getConfidenceColor(cat.confidence)}`}>Confidence: {cat.confidence}</span>
                </div>
                <div className="space-y-2 text-xs text-gray-500">
                    <div className="flex items-center justify-between"
                         title={cat.tractive_update_time ? new Date(cat.tractive_update_time).toLocaleString() : 'N/A'}>
                        <span className="flex items-center gap-1.5"><Satellite className="w-3 h-3"/> Last tracker update:</span>
                        <span>{formatRelativeTime(cat.tractive_update_time)}</span>
                    </div>
                    <div className="flex items-center justify-between"
                         title={cat.surepet_update_time ? new Date(cat.surepet_update_time).toLocaleString() : 'N/A'}>
                        <span className="flex items-center gap-1.5"><DoorOpen className="w-3 h-3"/> Last cat flap event:</span>
                        <span>{formatRelativeTime(cat.surepet_update_time)}</span>
                    </div>
                    <div className="flex items-center justify-between"
                         title={lastRefresh ? lastRefresh.toLocaleString() : 'N/A'}>
                        <span className="flex items-center gap-1.5"><RefreshCw className="w-3 h-3"/> Dashboard refreshed:</span>
                        <span>{formatRelativeTime(lastRefresh)}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default StatusCard;