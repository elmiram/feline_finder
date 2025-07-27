import React from 'react';
import {Battery} from 'lucide-react';

const BatteryStatus = ({level, isCharging}) => {
    if (level === null || typeof level === 'undefined') return null;
    let color = 'text-green-600';
    if (level <= 20) color = 'text-red-600';
    else if (level <= 50) color = 'text-yellow-600';
    const chargingColor = 'text-blue-600';

    return (
        <div className={`flex items-center space-x-1.5 text-sm font-medium ${isCharging ? chargingColor : color}`}>
            <Battery className="w-5 h-5"/>
            <span>{level}%{isCharging ? ' (Charging)' : ''}</span>
        </div>
    );
};

export default BatteryStatus;