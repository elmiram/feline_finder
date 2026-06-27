import React, {useState} from 'react';
import {Home, TreeDeciduous, Eye, User, MapPin} from 'lucide-react';
import {formatRelativeTime, formatEventTime} from '../utils/time';

const ZONE_CHANGES_DEFAULT_LIMIT = 3;

const EventLog = ({events, zoneChanges}) => {
    const [showAllZones, setShowAllZones] = useState(false);

    const getIcon = (e) => {
        const source = e.source ?? e.event_source;
        if (source === 0) return e.direction === 1 ? <Home className="w-4 h-4 text-blue-500"/> :
            <TreeDeciduous className="w-4 h-4 text-green-500"/>;
        if (source === 1) return <User className="w-4 h-4 text-purple-500"/>;
        if (source === 2) return <Eye className="w-4 h-4 text-yellow-500"/>;
        return null;
    };

    const getText = (e) => {
        const source = e.source ?? e.event_source;
        if (source === 0) return e.direction === 1 ? 'Entered flap' : 'Exited flap';
        if (source === 1) return e.direction === 1 ? 'Set to Inside' : 'Set to Outside';
        if (source === 2) return e.direction === 1 ? 'Looked from Inside' : 'Looked from Outside';
        return 'Unknown Event';
    };

    const hasEvents = events && events.length > 0;
    const hasZoneChanges = zoneChanges && zoneChanges.length > 0;
    const visibleZoneChanges = showAllZones ? zoneChanges : (zoneChanges || []).slice(0, ZONE_CHANGES_DEFAULT_LIMIT);
    const hiddenZoneCount = hasZoneChanges ? Math.max(0, zoneChanges.length - ZONE_CHANGES_DEFAULT_LIMIT) : 0;

    if (!hasEvents && !hasZoneChanges) {
        return <div className="text-center text-sm text-gray-400 py-4">No recent events</div>;
    }

    return (
        <div className="mt-4 space-y-4">
            {hasEvents && (
                <div>
                    <h4 className="font-bold text-gray-700 mb-2 text-center">Recent Activity</h4>
                    <ul className="space-y-2">
                        {events.map((e) => (
                            <li key={e.surepet_event_id}
                                className="flex items-center justify-between text-sm p-2 bg-gray-50 rounded-md"
                                title={new Date(e.timestamp).toLocaleString()}>
                                <span className="flex items-center gap-2 text-gray-700 truncate">
                                    {getIcon(e)}
                                    <span className="truncate">
                                        {getText(e)} at <span className="font-medium text-gray-800">{formatEventTime(e.timestamp)}</span>
                                    </span>
                                </span>
                                <span className="text-gray-500 flex-shrink-0 ml-4">
                                    {formatRelativeTime(e.timestamp)}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {hasZoneChanges && (
                <div>
                    <h4 className="font-bold text-gray-700 mb-2 text-center">Recent Zone Changes</h4>
                    <ul className="space-y-2">
                        {visibleZoneChanges.map((z, i) => (
                            <li key={i}
                                className="flex items-center justify-between text-sm p-2 bg-gray-50 rounded-md"
                                title={new Date(z.entered_at).toLocaleString()}>
                                <span className="flex items-center gap-2 text-gray-700 truncate">
                                    <MapPin className="w-4 h-4 text-indigo-400 flex-shrink-0"/>
                                    <span className="truncate">
                                        Entered <span className="font-medium text-gray-800">{z.to_zone ?? 'unknown area'}</span>
                                        {z.from_zone && <span className="text-gray-400"> from {z.from_zone}</span>}
                                    </span>
                                </span>
                                <span className="text-gray-500 flex-shrink-0 ml-4">
                                    {formatRelativeTime(z.entered_at)}
                                </span>
                            </li>
                        ))}
                    </ul>
                    {hiddenZoneCount > 0 && (
                        <button
                            onClick={() => setShowAllZones(!showAllZones)}
                            className="mt-2 text-xs text-blue-500 hover:text-blue-700 w-full text-center py-1">
                            {showAllZones ? 'Show less' : `Show ${hiddenZoneCount} more`}
                        </button>
                    )}
                </div>
            )}
        </div>
    );
};

export default EventLog;
