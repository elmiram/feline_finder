import React, {useState, useEffect, useRef} from 'react';
import {API_BASE_URL} from './constants';
import DashboardView from './views/DashboardView';
import HistoryView from './views/HistoryView';
import SettingsView from './views/SettingsView';
import {Activity, BarChart2, Settings} from 'lucide-react';

const NAV_TABS = [
    {id: 'dashboard', label: 'Live', fullLabel: 'Live Dashboard', Icon: Activity},
    {id: 'history', label: 'History', fullLabel: 'Historical Analysis', Icon: BarChart2},
    {id: 'settings', label: 'Settings', fullLabel: 'Settings', Icon: Settings},
];

export default function App() {
    const [activeView, setActiveView] = useState('dashboard');

    const [catsStatus, setCatsStatus] = useState({});
    const [knownZones, setKnownZones] = useState({});
    const [statusLoading, setStatusLoading] = useState(true);
    const [statusError, setStatusError] = useState(null);
    const [lastRefreshTime, setLastRefreshTime] = useState(null);
    const [allCatNames, setAllCatNames] = useState([]);

    const [autoRefresh, setAutoRefresh] = useState(true);
    const statusIntervalRef = useRef(null);

    useEffect(() => {
        const fetchInitialData = async () => {
            setStatusLoading(true);
            setStatusError(null);
            try {
                const [statusRes, zonesRes, catsRes] = await Promise.all([
                    fetch(`${API_BASE_URL}/api/status`),
                    fetch(`${API_BASE_URL}/api/zones`),
                    fetch(`${API_BASE_URL}/api/cats`),
                ]);
                if (!statusRes.ok) throw new Error(`HTTP error! status: ${statusRes.status}`);
                if (!zonesRes.ok) throw new Error(`HTTP error! status: ${zonesRes.status}`);
                if (!catsRes.ok) throw new Error(`HTTP error! status: ${catsRes.status}`);

                const statusData = await statusRes.json();
                const zonesData = await zonesRes.json();
                const catsData = await catsRes.json();

                setCatsStatus(statusData);
                setKnownZones(zonesData);
                setAllCatNames(catsData);
                setLastRefreshTime(new Date());
            } catch (e) {
                console.error("Failed to fetch initial data:", e);
                setStatusError("Could not connect to API server. Please ensure it is running and the IP address is correct.");
            } finally {
                setStatusLoading(false);
            }
        };
        fetchInitialData();
    }, []);

    useEffect(() => {
        const fetchStatus = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/api/status`);
                if (!response.ok) {
                    console.error(`Auto-refresh failed: ${response.status}`);
                    return;
                }
                const data = await response.json();
                setCatsStatus(data);
                setLastRefreshTime(new Date());
            } catch (e) {
                console.error("Failed to fetch cat status during auto-refresh:", e);
            }
        };

        if (statusIntervalRef.current) clearInterval(statusIntervalRef.current);
        if (autoRefresh && activeView === 'dashboard') {
            statusIntervalRef.current = setInterval(fetchStatus, 30000);
        }

        return () => {
            if (statusIntervalRef.current) clearInterval(statusIntervalRef.current);
        };
    }, [autoRefresh, activeView]);

    return (
        <div className="bg-gray-50 min-h-screen font-sans">
            <div className="max-w-6xl mx-auto p-4 sm:p-6 lg:p-8 pb-20 sm:pb-6 lg:pb-8">
                <header className="mb-4 sm:mb-8 text-center">
                    <h1 className="text-3xl sm:text-5xl font-extrabold text-gray-800 tracking-tight">FelineFinder</h1>
                    <p className="mt-2 text-lg text-gray-500 hidden sm:block">Cat tracking and behavior analysis</p>
                </header>

                <div className="hidden sm:block mb-8 border-b border-gray-200">
                    <nav className="flex -mb-px space-x-6">
                        {NAV_TABS.map(({id, fullLabel}) => (
                            <button key={id} onClick={() => setActiveView(id)}
                                    className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-lg ${activeView === id ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>
                                {fullLabel}
                            </button>
                        ))}
                    </nav>
                </div>

                {activeView === 'dashboard' && (
                    <DashboardView
                        catsStatus={catsStatus}
                        statusLoading={statusLoading}
                        statusError={statusError}
                        lastRefreshTime={lastRefreshTime}
                        autoRefresh={autoRefresh}
                        setAutoRefresh={setAutoRefresh}
                    />
                )}

                {activeView === 'history' && (
                    <HistoryView
                        catNames={allCatNames}
                        knownZones={knownZones}
                    />
                )}

                {activeView === 'settings' && (
                    <SettingsView />
                )}
            </div>

            <nav className="sm:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200" style={{zIndex: 100}}>
                <div className="flex">
                    {NAV_TABS.map(({id, label, Icon}) => (
                        <button key={id} onClick={() => setActiveView(id)}
                                className={`flex-1 flex flex-col items-center py-3 text-xs font-medium ${activeView === id ? 'text-blue-600' : 'text-gray-500'}`}>
                            <Icon className={`w-5 h-5 mb-1 ${activeView === id ? 'text-blue-600' : 'text-gray-400'}`}/>
                            {label}
                        </button>
                    ))}
                </div>
            </nav>
        </div>
    );
}
