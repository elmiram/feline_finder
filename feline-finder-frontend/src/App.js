import React, {useState, useEffect, useRef} from 'react';
import {API_BASE_URL} from './constants';
import DashboardView from './views/DashboardView';
import HistoryView from './views/HistoryView';
import SettingsView from './views/SettingsView';

export default function App() {
    const [activeView, setActiveView] = useState('dashboard');

    // State for live status data, shared by both views
    const [catsStatus, setCatsStatus] = useState({});
    const [knownZones, setKnownZones] = useState({});
    const [statusLoading, setStatusLoading] = useState(true);
    const [statusError, setStatusError] = useState(null);
    const [lastRefreshTime, setLastRefreshTime] = useState(null);
    const [allCatNames, setAllCatNames] = useState([]);

    // State for auto-refresh controls
    const [autoRefresh, setAutoRefresh] = useState(true);
    const statusIntervalRef = useRef(null);

    // Fetch Live Status and Zones on initial load
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


    // Handle Auto-Refresh for the dashboard
    useEffect(() => {
        const fetchStatus = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/api/status`);
                if (!response.ok) {
                    // Don't throw an error, just log it, so a temporary network blip doesn't kill the page
                    console.error(`Auto-refresh failed: ${response.status}`);
                    return;
                }
                ;
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
        <div className="bg-gray-50 min-h-screen font-sans p-4 sm:p-6 lg:p-8">
            <div className="max-w-6xl mx-auto">
                <header className="mb-8 text-center">
                    <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-800 tracking-tight">FelineFinder</h1>
                    <p className="mt-2 text-lg text-gray-500">Cat tracking and behavior analysis</p>
                </header>

                <div className="mb-8 border-b border-gray-200">
                    <nav className="flex -mb-px space-x-2 sm:space-x-6">
                        <button onClick={() => setActiveView('dashboard')}
                                className={`whitespace-nowrap py-3 sm:py-4 px-1 border-b-2 font-medium text-sm sm:text-lg ${activeView === 'dashboard' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>
                            Live Dashboard
                        </button>
                        <button onClick={() => setActiveView('history')}
                                className={`whitespace-nowrap py-3 sm:py-4 px-1 border-b-2 font-medium text-sm sm:text-lg ${activeView === 'history' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>
                            Historical Analysis
                        </button>
                        <button onClick={() => setActiveView('settings')}
                                className={`whitespace-nowrap py-3 sm:py-4 px-1 border-b-2 font-medium text-sm sm:text-lg ${activeView === 'settings' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>
                            Settings
                        </button>
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
        </div>
    );
}