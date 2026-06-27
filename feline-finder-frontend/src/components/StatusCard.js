import React from 'react';
import {Home, TreeDeciduous, Battery, AlertTriangle, PawPrint, Satellite, DoorOpen, RefreshCw} from 'lucide-react';
import BatteryStatus from './BatteryStatus';
import {formatRelativeTime} from '../utils/time';

const StatusCard = ({cat, lastRefresh}) => {
    const getConfidenceColor = (c) => (c === 'High' ? 'bg-green-100 text-green-800' : c === 'Medium' ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800');

    const getStatusIcon = (s) => {
        const cls = "w-4 h-4 sm:w-6 sm:h-6 flex-shrink-0";
        const ls = s.toLowerCase();
        if (ls.includes('home')) return <Home className={`${cls} text-blue-500`}/>;
        if (ls.includes('outside')) return <TreeDeciduous className={`${cls} text-green-500`}/>;
        if (ls.includes('charging')) return <Battery className={`${cls} text-yellow-500`}/>;
        return <AlertTriangle className={`${cls} text-gray-500`}/>;
    };

    return (
        <div className="bg-white rounded-2xl shadow-lg p-3 sm:p-6 flex flex-col justify-between transform hover:scale-105 transition-transform duration-300">
            <div>
                <div className="flex items-center justify-between mb-1 sm:mb-2">
                    <div className="flex items-center space-x-2 sm:space-x-3 min-w-0">
                        <div className="bg-gray-100 p-2 sm:p-3 rounded-full flex-shrink-0">
                            <PawPrint className="w-4 h-4 sm:w-6 sm:h-6 text-gray-600"/>
                        </div>
                        <h2 className="text-lg sm:text-2xl font-bold text-gray-800 truncate">{cat.name}</h2>
                    </div>
                    <BatteryStatus level={cat.battery_level} isCharging={cat.is_charging}/>
                </div>
                <div className="flex items-start space-x-2 sm:space-x-3 my-2 sm:my-4">
                    {getStatusIcon(cat.status)}
                    <div className="min-w-0">
                        <p className="text-sm sm:text-xl font-semibold text-gray-700 leading-tight">{cat.status}</p>
                        {cat.location_detail && (
                            <p className="text-xs sm:text-sm text-blue-600 font-medium truncate">{cat.location_detail}</p>
                        )}
                    </div>
                </div>
                <p className="text-gray-500 text-xs sm:text-sm mb-2 sm:mb-4 hidden sm:block">{cat.evidence}</p>
            </div>
            <div className="border-t pt-2 sm:pt-4 mt-2 sm:mt-4">
                <div className="flex justify-between items-center mb-1 sm:mb-3">
                    <span className={`px-2 py-0.5 sm:px-3 sm:py-1 text-xs sm:text-sm font-semibold rounded-full ${getConfidenceColor(cat.confidence)}`}>
                        <span className="sm:hidden">{cat.confidence}</span>
                        <span className="hidden sm:inline">Confidence: {cat.confidence}</span>
                    </span>
                </div>
                <div className="hidden sm:block space-y-2 text-xs text-gray-500">
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
