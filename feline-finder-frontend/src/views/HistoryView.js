import React, { useState, useEffect, useRef } from 'react';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { API_BASE_URL } from '../constants';
import { formatDate } from '../utils/time';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorDisplay from '../components/ErrorDisplay';
import TerritoryMap from '../components/TerritoryMap';
import { ChevronDown } from 'lucide-react';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

const HistoryView = ({ catNames, knownZones }) => {
    const [historyCat, setHistoryCat] = useState(catNames[0] || '');
    const [windowSizeDays, setWindowSizeDays] = useState(7);

    // Slider: visual position updates immediately; debounced value triggers data fetches
    const [sliderEndDate, setSliderEndDate] = useState(new Date());
    const [historyEndDate, setHistoryEndDate] = useState(new Date());
    const debounceTimerRef = useRef(null);

    const [mapViewType, setMapViewType] = useState('points');

    const [filteredGps, setFilteredGps] = useState([]);
    const [territoryPolygon, setTerritoryPolygon] = useState([]);

    const [historyLoading, setHistoryLoading] = useState(true);
    const [historyError, setHistoryError] = useState(null);
    const isInitialCatLoad = useRef(true);

    // Collapsed by default on mobile so the map has priority
    const [controlsOpen, setControlsOpen] = useState(() => window.innerWidth >= 640);

    const timelineStartDate = new Date(new Date().setDate(new Date().getDate() - 365));

    // --- Territory trend chart state ---
    const [trendLoading, setTrendLoading] = useState(true);
    const [arthurTrend, setArthurTrend] = useState([]);
    const [kingTrend, setKingTrend] = useState([]);

    // --- Overlap stat state ---
    const [overlapLoading, setOverlapLoading] = useState(true);
    const [overlapData, setOverlapData] = useState(null);

    useEffect(() => {
        isInitialCatLoad.current = true;
    }, [historyCat]);

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
                const gpsRes = await fetch(
                    `${API_BASE_URL}/api/history/gps?cat_name=${historyCat}&start_date=${startDate.toISOString()}&end_date=${endDate.toISOString()}`
                );

                if (!gpsRes.ok) throw new Error('Failed to fetch history data');
                const gpsData = await gpsRes.json();

                setFilteredGps(gpsData.positions.map(p => ({ ...p, time: new Date(p.time) })));
                setTerritoryPolygon(gpsData.territory_polygon);
            } catch (e) {
                console.error('Failed to fetch windowed history:', e);
                setHistoryError('Could not load historical data for this window.');
            } finally {
                if (isInitialCatLoad.current) {
                    setHistoryLoading(false);
                    isInitialCatLoad.current = false;
                }
            }
        };

        fetchHistoryForWindow();
    }, [historyCat, windowSizeDays, historyEndDate]);

    // Fetch territory trend data once on mount
    useEffect(() => {
        const fetchTrends = async () => {
            setTrendLoading(true);
            try {
                const [arthurRes, kingRes] = await Promise.all([
                    fetch(`${API_BASE_URL}/api/territory/trend?cat_name=Arthur`),
                    fetch(`${API_BASE_URL}/api/territory/trend?cat_name=King`),
                ]);
                const arthurJson = arthurRes.ok ? await arthurRes.json() : { trend: [] };
                const kingJson = kingRes.ok ? await kingRes.json() : { trend: [] };

                // Filter to monthly data only for a cleaner trend
                setArthurTrend((arthurJson.trend || []).filter(t => t.period_type === 'month'));
                setKingTrend((kingJson.trend || []).filter(t => t.period_type === 'month'));
            } catch (e) {
                console.error('Failed to fetch territory trends:', e);
            } finally {
                setTrendLoading(false);
            }
        };
        fetchTrends();
    }, []);

    // Fetch overlap data for current month once on mount
    useEffect(() => {
        const fetchOverlap = async () => {
            setOverlapLoading(true);
            const now = new Date();
            const periodStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
            try {
                const res = await fetch(
                    `${API_BASE_URL}/api/territory/overlap?period_start=${periodStart}&period_type=month`
                );
                if (res.ok) {
                    const data = await res.json();
                    setOverlapData(data);
                }
            } catch (e) {
                console.error('Failed to fetch overlap data:', e);
            } finally {
                setOverlapLoading(false);
            }
        };
        fetchOverlap();
    }, []);

    // Handler for slider: update visual position immediately, debounce the data-triggering state
    const handleSliderChange = (e) => {
        const newDate = new Date(Number(e.target.value));
        setSliderEndDate(newDate);

        if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = setTimeout(() => {
            setHistoryEndDate(newDate);
        }, 300);
    };

    // Build territory trend chart data
    // Collect all unique month labels from both datasets, sorted
    const labelsSet = new Set([
        ...arthurTrend.map(t => t.period_start.slice(0, 7)),
        ...kingTrend.map(t => t.period_start.slice(0, 7)),
    ]);
    const allTrendLabels = [...labelsSet].sort();

    const trendChartData = {
        labels: allTrendLabels,
        datasets: [
            {
                label: 'Arthur',
                data: allTrendLabels.map(label => {
                    const entry = arthurTrend.find(t => t.period_start.slice(0, 7) === label);
                    return entry ? entry.area_m2 / 1_000_000 : null;
                }),
                borderColor: '#F59E0B',
                backgroundColor: 'rgba(245,158,11,0.1)',
                tension: 0.3,
                spanGaps: true,
            },
            {
                label: 'King',
                data: allTrendLabels.map(label => {
                    const entry = kingTrend.find(t => t.period_start.slice(0, 7) === label);
                    return entry ? entry.area_m2 / 1_000_000 : null;
                }),
                borderColor: '#8B5CF6',
                backgroundColor: 'rgba(139,92,246,0.1)',
                tension: 0.3,
                spanGaps: true,
            },
        ],
    };

    const trendChartOptions = {
        responsive: true,
        plugins: {
            legend: { position: 'top' },
            title: { display: false },
            tooltip: {
                callbacks: {
                    label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y !== null ? ctx.parsed.y.toFixed(3) + ' km²' : 'N/A'}`,
                },
            },
        },
        scales: {
            y: {
                title: { display: true, text: 'Area (km²)' },
                beginAtZero: true,
            },
            x: {
                title: { display: true, text: 'Month' },
            },
        },
    };

    // Overlap card content
    const renderOverlapCard = () => {
        if (overlapLoading) return <p className="text-gray-400 text-sm">Loading...</p>;
        if (!overlapData) return <p className="text-gray-400 text-sm">Data unavailable</p>;

        const { overlap, missing } = overlapData;

        if (missing && missing.length > 0) {
            return <p className="text-gray-500 text-sm">Data unavailable for {missing.join(', ')}</p>;
        }

        if (!overlap) {
            return <p className="text-gray-500 text-sm">No overlap data for current month</p>;
        }

        return (
            <p className="text-2xl font-bold text-purple-600">
                {parseFloat(overlap.overlap_pct).toFixed(1)}%
                <span className="text-sm font-normal text-gray-500 ml-2">Arthur ∩ King (current month)</span>
            </p>
        );
    };

    return (
        <div>
            <div className="bg-white rounded-2xl shadow-lg mb-4 md:mb-6">
                {/* Mobile toggle header */}
                <button
                    className="sm:hidden w-full flex items-center justify-between p-4 font-medium text-gray-700"
                    onClick={() => setControlsOpen(!controlsOpen)}>
                    <span>Filter Controls</span>
                    <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${controlsOpen ? 'rotate-180' : ''}`} />
                </button>

                <div className={`${controlsOpen ? 'block' : 'hidden'} sm:block p-4 md:p-6`}>
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
                                <button onClick={() => setMapViewType('heatmap')}
                                    className={`w-full py-1.5 text-sm rounded-md ${mapViewType === 'heatmap' ? 'bg-white shadow font-medium' : 'text-gray-600'}`}>Heatmap
                                </button>
                            </div>
                        </div>
                    </div>
                    <div>
                        <label htmlFor="timeline-slider" className="block text-xs md:text-sm font-medium text-gray-700 mb-2">Timeline End Date</label>
                        <input
                            type="range"
                            id="timeline-slider"
                            min={timelineStartDate.getTime()}
                            max={new Date().getTime()}
                            value={sliderEndDate.getTime()}
                            onChange={handleSliderChange}
                            step={86400000}
                            className="w-full h-3 md:h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                        />
                        <div className="flex justify-between text-xs text-gray-500 mt-2">
                            <span>{formatDate(new Date(sliderEndDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000))}</span>
                            <span>{formatDate(sliderEndDate)}</span>
                        </div>
                    </div>
                </div>
            </div>

            {historyLoading ? <LoadingSpinner /> : historyError ? <ErrorDisplay message={historyError} /> : (
                <div className="bg-white rounded-2xl shadow-lg p-3 md:p-6">
                    <h3 className="text-base md:text-xl font-bold text-gray-800 mb-3 md:mb-4">Territory Map</h3>
                    <TerritoryMap
                        gpsPoints={filteredGps}
                        zones={knownZones}
                        territory={territoryPolygon}
                        viewType={mapViewType}
                        catName={historyCat}
                        historyEndDate={historyEndDate}
                        historyStartDate={new Date(historyEndDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000)}
                    />
                </div>
            )}

            {/* Territory Area Trend */}
            <div className="bg-white rounded-2xl shadow-lg p-4 md:p-6 mt-4 md:mt-6">
                <h3 className="text-base md:text-xl font-bold text-gray-800 mb-3 md:mb-4">Territory Area Trend</h3>
                {trendLoading ? (
                    <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading trend data...</div>
                ) : allTrendLabels.length === 0 ? (
                    <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No trend data available</div>
                ) : (
                    <Line data={trendChartData} options={trendChartOptions} />
                )}
            </div>

            {/* Overlap Stat Card */}
            <div className="bg-white rounded-2xl shadow-lg p-4 md:p-6 mt-4 md:mt-6">
                <h3 className="text-base md:text-xl font-bold text-gray-800 mb-2">Territory Overlap</h3>
                {renderOverlapCard()}
            </div>
        </div>
    );
};

export default HistoryView;
