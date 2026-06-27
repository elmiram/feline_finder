import React, {useState, useEffect, useRef} from 'react';
import {API_BASE_URL} from '../constants';
import {formatDate} from '../utils/time';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorDisplay from '../components/ErrorDisplay';
import TerritoryMap from '../components/TerritoryMap';

const HistoryView = ({catNames, knownZones}) => {
    // State for user controls
    const [historyCat, setHistoryCat] = useState(catNames[0] || '');
    const [windowSizeDays, setWindowSizeDays] = useState(7);
    const [historyEndDate, setHistoryEndDate] = useState(new Date());
    const [mapViewType, setMapViewType] = useState('points'); // 'points' or 'territory'

    // State for data
    const [filteredGps, setFilteredGps] = useState([]);
    const [territoryPolygon, setTerritoryPolygon] = useState([]);
    // const [filteredEvents, setFilteredEvents] = useState([]); // For time chart if re-enabled

    // State for loading/error
    const [historyLoading, setHistoryLoading] = useState(true);
    const [historyError, setHistoryError] = useState(null);
    const isInitialCatLoad = useRef(true);

    const timelineStartDate = new Date(new Date().setDate(new Date().getDate() - 365));
    const historyStartDate = new Date(historyEndDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000);

    // Set a flag when the cat changes to trigger the loading spinner
    useEffect(() => {
        isInitialCatLoad.current = true;
    }, [historyCat]);

    // Fetch History Data when controls change
    useEffect(() => {
        if (!historyCat) return;

        const fetchHistoryForWindow = async () => {
            if (isInitialCatLoad.current) {
                setHistoryLoading(true);
            }
            setHistoryError(null);

            const endDate = historyEndDate;
            const startDate = new Date(endDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000);

            try {
                // For now, we only need the GPS data for the map.
                const gpsRes = await fetch(`${API_BASE_URL}/api/history/gps?cat_name=${historyCat}&start_date=${startDate.toISOString()}&end_date=${endDate.toISOString()}`);

                if (!gpsRes.ok) throw new Error('Failed to fetch history data');
                const gpsData = await gpsRes.json();

                setFilteredGps(gpsData.positions.map(p => ({...p, time: new Date(p.time)})));
                setTerritoryPolygon(gpsData.territory_polygon);

            } catch (e) {
                console.error("Failed to fetch windowed history:", e);
                setHistoryError("Could not load historical data for this window.");
            } finally {
                if (isInitialCatLoad.current) {
                    setHistoryLoading(false);
                    isInitialCatLoad.current = false;
                }
            }
        };

        fetchHistoryForWindow();
    }, [historyCat, windowSizeDays, historyEndDate]);


    return (
        <div>
            <div className="bg-white rounded-2xl shadow-lg p-4 md:p-6 mb-4 md:mb-6">
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-6 mb-4 md:mb-6">
                    <div>
                        <label htmlFor="cat-select" className="block text-xs md:text-sm font-medium text-gray-700 mb-1">Cat</label>
                        <select id="cat-select" value={historyCat} onChange={(e) => setHistoryCat(e.target.value)}
                                className="w-full p-2 text-sm border border-gray-300 rounded-lg shadow-sm">
                            {catNames.map(name => <option key={name} value={name}>{name}</option>)}
                        </select>
                    </div>
                    <div>
                        <label htmlFor="window-select" className="block text-xs md:text-sm font-medium text-gray-700 mb-1">Window</label>
                        <select id="window-select" value={windowSizeDays}
                                onChange={(e) => setWindowSizeDays(Number(e.target.value))}
                                className="w-full p-2 text-sm border border-gray-300 rounded-lg shadow-sm">
                            <option value="7">7 Days</option>
                            <option value="14">14 Days</option>
                            <option value="30">30 Days</option>
                        </select>
                    </div>
                    <div className="col-span-2 md:col-span-1">
                        <label className="block text-xs md:text-sm font-medium text-gray-700 mb-1">View</label>
                        <div className="flex items-center space-x-2 bg-gray-100 p-1 rounded-lg">
                            <button onClick={() => setMapViewType('points')}
                                    className={`w-full py-1.5 text-sm rounded-md ${mapViewType === 'points' ? 'bg-white shadow font-medium' : 'text-gray-600'}`}>Points
                            </button>
                            <button onClick={() => setMapViewType('territory')}
                                    className={`w-full py-1.5 text-sm rounded-md ${mapViewType === 'territory' ? 'bg-white shadow font-medium' : 'text-gray-600'}`}>Territory
                            </button>
                        </div>
                    </div>
                </div>
                <div>
                    <label htmlFor="timeline-slider" className="block text-xs md:text-sm font-medium text-gray-700 mb-2">Timeline End Date</label>
                    <input type="range" id="timeline-slider" min={timelineStartDate.getTime()}
                           max={new Date().getTime()} value={historyEndDate.getTime()}
                           onChange={(e) => setHistoryEndDate(new Date(Number(e.target.value)))} step={86400000}
                           className="w-full h-3 md:h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                    <div className="flex justify-between text-xs text-gray-500 mt-2">
                        <span>{formatDate(historyStartDate)}</span>
                        <span>{formatDate(historyEndDate)}</span>
                    </div>
                </div>
            </div>
            {historyLoading ? <LoadingSpinner/> : historyError ? <ErrorDisplay message={historyError}/> : (
                <div className="bg-white rounded-2xl shadow-lg p-3 md:p-6">
                    <h3 className="text-base md:text-xl font-bold text-gray-800 mb-3 md:mb-4">Territory Map</h3>
                    <TerritoryMap
                        gpsPoints={filteredGps}
                        zones={knownZones}
                        territory={territoryPolygon}
                        viewType={mapViewType}
                    />
                </div>
            )}
        </div>
    );
};

export default HistoryView;