import React from 'react';
import {Home, TreeDeciduous, Eye, User} from 'lucide-react';
import {formatRelativeTime} from '../utils/time';

const EventLog = ({events}) => {
    if (!events || events.length === 0) {
        return <div className="text-center text-sm text-gray-400 py-4">No recent events</div>;
    }

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

    return (
        <div className="mt-4">
            <h4 className="font-bold text-gray-700 mb-2 text-center">Recent Activity</h4>
            <ul className="space-y-2">
                {events.map((e) => (
                    <li key={e.surepet_event_id}
                        className="flex items-center justify-between text-sm p-2 bg-gray-50 rounded-md">
                        <span className="flex items-center gap-2 text-gray-700">{getIcon(e)} {getText(e)}</span>
                        <span className="text-gray-400"
                              title={new Date(e.timestamp).toLocaleString()}>{formatRelativeTime(e.timestamp)}</span>
                    </li>
                ))}
            </ul>
        </div>
    );
};

export default EventLog;