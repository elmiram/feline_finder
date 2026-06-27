import React from 'react';
import {Battery} from 'lucide-react';

const BatteryStatus = ({level, isCharging}) => {
    if (level === null || typeof level === 'undefined') return null;
    let color = 'text-green-600';
    if (level <= 20) color = 'text-red-600';
    else if (level <= 50) color = 'text-yellow-600';
    const chargingColor = 'text-blue-600';

    return (
        <div className={`flex items-center space-x-1 sm:space-x-1.5 font-medium flex-shrink-0 ${isCharging ? chargingColor : color}`}>
            <Battery className="w-3 h-3 sm:w-5 sm:h-5"/>
            <span className="text-xs sm:text-sm">{level}%<span className="hidden sm:inline">{isCharging ? ' (Charging)' : ''}</span></span>
        </div>
    );
};

export default BatteryStatus;