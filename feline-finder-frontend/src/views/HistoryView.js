import React, { useState, useEffect, useRef } from 'react';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    PointElement,
    LineElement,
    ScatterController,
    Title,
    Tooltip,
    Legend,
} from 'chart.js';
import { Line, Bar, Scatter } from 'react-chartjs-2';
import { API_BASE_URL } from '../constants';
import { formatDate } from '../utils/time';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorDisplay from '../components/ErrorDisplay';
import TerritoryMap from '../components/TerritoryMap';
import { ChevronDown } from 'lucide-react';

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, ScatterController, Title, Tooltip, Legend);

// Colours shared between the trend chart and the all-cats territory legend
const CAT_COLORS = {
    Arthur: '#F59E0B',
    King: '#8B5CF6',
    Trixie: '#2DD4BF',
};

const ALL_CATS_SENTINEL = '__all__';

const HistoryView = ({ catNames, knownZones }) => {
    const [historyCat, setHistoryCat] = useState(ALL_CATS_SENTINEL);
    const [windowSizeDays, setWindowSizeDays] = useState(7);

    // Slider: visual position updates immediately; debounced value triggers data fetches
    const [sliderEndDate, setSliderEndDate] = useState(new Date());
    const [historyEndDate, setHistoryEndDate] = useState(new Date());
    const debounceTimerRef = useRef(null);

    const [mapViewType, setMapViewType] = useState('territory');

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

    // --- All-cats territory state ---
    // { Arthur: [...territories], King: [...], Trixie: [...] }
    const [allCatsTerritories, setAllCatsTerritories] = useState({});
    const [allCatsLoading, setAllCatsLoading] = useState(false);

    // --- Record distance state ---
    const [recordDistances, setRecordDistances] = useState({});

    // --- Zone dwell state ---
    const [dwellData, setDwellData] = useState([]);
    const [dwellLoading, setDwellLoading] = useState(false);
    const [trendModalZone, setTrendModalZone] = useState(null); // zone name string or null
    const [trendModalData, setTrendModalData] = useState([]);
    const [trendModalLoading, setTrendModalLoading] = useState(false);

    // --- Activity patterns state ---
    const [patternCat, setPatternCat] = useState(catNames[0] || 'Arthur');
    const [hourlyData, setHourlyData] = useState([]);
    const [hourlyLoading, setHourlyLoading] = useState(false);
    const [seasonalData, setSeasonalData] = useState([]);
    const [seasonalLoading, setSeasonalLoading] = useState(false);
    const [weatherCorrData, setWeatherCorrData] = useState([]);
    const [weatherCorrLoading, setWeatherCorrLoading] = useState(false);

    const isAllCatsMode = historyCat === ALL_CATS_SENTINEL;

    // Effective cat for dwell (Arthur fallback when All Cats selected)
    const dwellCat = isAllCatsMode ? 'Arthur' : historyCat;

    // Keep patternCat in sync with historyCat (except All Cats → Arthur)
    useEffect(() => {
        setPatternCat(isAllCatsMode ? 'Arthur' : historyCat);
    }, [historyCat, isAllCatsMode]);

    // If user switches away from territory view while in All Cats mode, revert to single cat
    useEffect(() => {
        if (isAllCatsMode && mapViewType !== 'territory') {
            setHistoryCat(catNames[0] || '');
        }
    }, [mapViewType, isAllCatsMode, catNames]);

    useEffect(() => {
        isInitialCatLoad.current = true;
    }, [historyCat]);

    // Fetch single-cat GPS history (skip when in All Cats mode)
    useEffect(() => {
        if (!historyCat || isAllCatsMode) return;

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
    }, [historyCat, windowSizeDays, historyEndDate, isAllCatsMode]);

    // Fetch all-cats weekly territories when entering All Cats mode
    useEffect(() => {
        if (!isAllCatsMode) return;
        // Only fetch cats we don't already have
        const missing = catNames.filter(name => !allCatsTerritories[name]);
        if (missing.length === 0) return;

        setAllCatsLoading(true);
        Promise.all(
            missing.map(name =>
                fetch(`${API_BASE_URL}/api/territory/weekly?cat_name=${encodeURIComponent(name)}&limit=52`)
                    .then(r => r.ok ? r.json() : { territories: [] })
                    .then(data => ({ name, territories: data.territories || [] }))
                    .catch(() => ({ name, territories: [] }))
            )
        ).then(results => {
            setAllCatsTerritories(prev => {
                const next = { ...prev };
                results.forEach(({ name, territories }) => { next[name] = territories; });
                return next;
            });
        }).finally(() => setAllCatsLoading(false));
    }, [isAllCatsMode, catNames, allCatsTerritories]);

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

                // Show all available data (weekly until monthly backfill is complete)
                setArthurTrend(arthurJson.trend || []);
                setKingTrend(kingJson.trend || []);
            } catch (e) {
                console.error('Failed to fetch territory trends:', e);
            } finally {
                setTrendLoading(false);
            }
        };
        fetchTrends();
    }, []);

    // Fetch overlap data for the most recent weekly period (once trend data is loaded)
    useEffect(() => {
        if (trendLoading) return;

        const fetchOverlap = async () => {
            setOverlapLoading(true);
            // Find the most recent period_start that exists in BOTH cats' trend arrays.
            // King's backfill may lag Arthur's, so using Arthur's latest alone can
            // produce "Data unavailable for King". Fall back to Arthur's latest if
            // there is no shared period at all.
            const arthurPeriods = new Set(arthurTrend.map(t => t.period_start));
            const sharedPeriods = kingTrend
                .map(t => t.period_start)
                .filter(p => arthurPeriods.has(p))
                .sort();
            const sharedPeriodStart = sharedPeriods[sharedPeriods.length - 1];

            const arthurPeriodsSorted = arthurTrend.map(t => t.period_start).sort();
            const fallbackPeriodStart = arthurPeriodsSorted[arthurPeriodsSorted.length - 1];

            const periodStart = sharedPeriodStart || fallbackPeriodStart;
            if (!periodStart) {
                setOverlapLoading(false);
                return;
            }
            try {
                const res = await fetch(
                    `${API_BASE_URL}/api/territory/overlap?period_start=${periodStart}&period_type=week`
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
    }, [trendLoading, arthurTrend, kingTrend]);

    // Fetch record distances for all cats once on mount
    useEffect(() => {
        const allCats = ['Arthur', 'King', 'Trixie'];
        Promise.all(
            allCats.map(name =>
                fetch(`${API_BASE_URL}/api/stats/farthest?cat_name=${encodeURIComponent(name)}`)
                    .then(r => r.ok ? r.json() : null)
                    .catch(() => null)
                    .then(data => ({ name, data }))
            )
        ).then(results => {
            const next = {};
            results.forEach(({ name, data }) => { if (data) next[name] = data; });
            setRecordDistances(next);
        });
    }, []);

    // Fetch zone dwell data whenever cat or date window changes
    useEffect(() => {
        if (!dwellCat) return;
        const endDate = historyEndDate;
        const startDate = new Date(endDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000);
        setDwellLoading(true);
        fetch(
            `${API_BASE_URL}/api/zones/dwell?cat_name=${encodeURIComponent(dwellCat)}&start_date=${startDate.toISOString()}&end_date=${endDate.toISOString()}`
        )
            .then(r => r.ok ? r.json() : [])
            .then(data => setDwellData(Array.isArray(data) ? data : []))
            .catch(() => setDwellData([]))
            .finally(() => setDwellLoading(false));
    }, [dwellCat, historyEndDate, windowSizeDays]);

    // Fetch zone monthly trend when a bar is clicked
    useEffect(() => {
        if (!trendModalZone || !dwellCat) return;
        setTrendModalLoading(true);
        setTrendModalData([]);
        fetch(
            `${API_BASE_URL}/api/zones/trend?cat_name=${encodeURIComponent(dwellCat)}&zone_name=${encodeURIComponent(trendModalZone)}`
        )
            .then(r => r.ok ? r.json() : [])
            .then(data => setTrendModalData(Array.isArray(data) ? data : []))
            .catch(() => setTrendModalData([]))
            .finally(() => setTrendModalLoading(false));
    }, [trendModalZone, dwellCat]);

    // Fetch 24-hour activity fractions
    useEffect(() => {
        if (!patternCat) return;
        setHourlyLoading(true);
        fetch(`${API_BASE_URL}/api/activity/hourly?cat_name=${encodeURIComponent(patternCat)}`)
            .then(r => r.ok ? r.json() : [])
            .then(data => setHourlyData(Array.isArray(data) ? data : []))
            .catch(() => setHourlyData([]))
            .finally(() => setHourlyLoading(false));
    }, [patternCat]);

    // Fetch seasonal outdoor hours
    useEffect(() => {
        if (!patternCat) return;
        setSeasonalLoading(true);
        fetch(`${API_BASE_URL}/api/activity/seasonal?cat_name=${encodeURIComponent(patternCat)}`)
            .then(r => r.ok ? r.json() : [])
            .then(data => setSeasonalData(Array.isArray(data) ? data : []))
            .catch(() => setSeasonalData([]))
            .finally(() => setSeasonalLoading(false));
    }, [patternCat]);

    // Fetch weather correlation data
    useEffect(() => {
        if (!patternCat) return;
        setWeatherCorrLoading(true);
        fetch(`${API_BASE_URL}/api/activity/weather_correlation?cat_name=${encodeURIComponent(patternCat)}`)
            .then(r => r.ok ? r.json() : [])
            .then(data => setWeatherCorrData(Array.isArray(data) ? data : []))
            .catch(() => setWeatherCorrData([]))
            .finally(() => setWeatherCorrLoading(false));
    }, [patternCat]);

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
                borderColor: CAT_COLORS.Arthur,
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
                borderColor: CAT_COLORS.King,
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
                title: { display: true, text: 'Period' },
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
            return <p className="text-gray-500 text-sm">No overlap data for current week</p>;
        }

        return (
            <p className="text-2xl font-bold text-purple-600">
                {parseFloat(overlap.overlap_pct).toFixed(1)}%
                <span className="text-sm font-normal text-gray-500 ml-2">Arthur ∩ King (current week)</span>
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
                            <select
                                id="cat-select"
                                value={historyCat}
                                onChange={(e) => setHistoryCat(e.target.value)}
                                className="w-full p-2 text-sm border border-gray-300 rounded-lg shadow-sm"
                            >
                                {catNames.map(name => <option key={name} value={name}>{name}</option>)}
                                <option value={ALL_CATS_SENTINEL}>
                                    {mapViewType === 'territory' ? 'All Cats' : 'All Cats (Territory only)'}
                                </option>
                            </select>
                            {isAllCatsMode && mapViewType !== 'territory' && (
                                <p className="text-xs text-amber-600 mt-1">All Cats is only available in Territory view</p>
                            )}
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

            {isAllCatsMode ? (
                <div className="bg-white rounded-2xl shadow-lg p-3 md:p-6">
                    <h3 className="text-base md:text-xl font-bold text-gray-800 mb-3 md:mb-4">Territory Map</h3>
                    <TerritoryMap
                        gpsPoints={[]}
                        zones={knownZones}
                        territory={[]}
                        viewType="territory"
                        catName={null}
                        historyEndDate={historyEndDate}
                        historyStartDate={new Date(historyEndDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000)}
                        allCatsTerritories={allCatsTerritories}
                        allCatsLoading={allCatsLoading}
                        catColors={CAT_COLORS}
                    />
                    {/* All-cats legend */}
                    <div className="flex flex-wrap gap-4 mt-3 justify-center">
                        {catNames.map(name => (
                            <div key={name} className="flex items-center gap-1.5 text-sm text-gray-700">
                                <span
                                    className="inline-block w-4 h-4 rounded-sm"
                                    style={{ backgroundColor: CAT_COLORS[name] || '#999', opacity: 0.7 }}
                                />
                                {name}
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                historyLoading ? <LoadingSpinner /> : historyError ? <ErrorDisplay message={historyError} /> : (
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
                )
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

            {/* Record Distance from Home */}
            <div className="bg-white rounded-2xl shadow-lg p-4 md:p-6 mt-4 md:mt-6">
                <h3 className="text-base md:text-xl font-bold text-gray-800 mb-3 md:mb-4">Record Distance from Home</h3>
                <div className="flex flex-wrap gap-4">
                    {['Arthur', 'King', 'Trixie'].map(name => {
                        const rec = recordDistances[name];
                        const dateStr = rec && rec.timestamp
                            ? new Date(rec.timestamp.replace(' ', 'T') + 'Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                            : null;
                        return (
                            <div key={name} className="flex-1 min-w-40 bg-gray-50 rounded-xl px-4 py-3 border border-gray-100">
                                <p className="text-xs font-semibold text-gray-500 mb-1">{name}</p>
                                {rec && rec.distance_km !== null ? (
                                    <>
                                        <p className="text-xl font-bold text-gray-800">{rec.distance_km.toFixed(2)} km</p>
                                        {dateStr && <p className="text-xs text-gray-400 mt-0.5">{dateStr}</p>}
                                    </>
                                ) : (
                                    <p className="text-sm text-gray-400">No data</p>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Zone Dwell Time */}
            <div className="bg-white rounded-2xl shadow-lg p-4 md:p-6 mt-4 md:mt-6">
                <h3 className="text-base md:text-xl font-bold text-gray-800 mb-1">Zone Dwell Time</h3>
                {isAllCatsMode && (
                    <p className="text-xs text-amber-600 mb-3">Zone dwell shown for Arthur (single-cat only)</p>
                )}
                {dwellLoading ? (
                    <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading dwell data...</div>
                ) : dwellData.length === 0 ? (
                    <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No zone data for this window</div>
                ) : (() => {
                    const useHours = dwellData[0].total_minutes > 120;
                    const barLabels = dwellData.map(z => z.zone_name);
                    const barValues = dwellData.map(z => useHours ? +(z.total_minutes / 60).toFixed(2) : z.total_minutes);
                    const dwellBarData = {
                        labels: barLabels,
                        datasets: [{
                            label: useHours ? 'Hours' : 'Minutes',
                            data: barValues,
                            backgroundColor: '#3B82F6',
                            borderRadius: 4,
                        }],
                    };
                    const dwellBarOptions = {
                        indexAxis: 'y',
                        responsive: true,
                        onClick: (_evt, elements) => {
                            if (elements.length > 0) {
                                const idx = elements[0].index;
                                setTrendModalZone(dwellData[idx].zone_name);
                            }
                        },
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: (ctx) => {
                                        const z = dwellData[ctx.dataIndex];
                                        return `${ctx.parsed.x} ${useHours ? 'h' : 'min'} · ${z.pct_of_total}% · ${z.visit_count} visit${z.visit_count !== 1 ? 's' : ''}`;
                                    },
                                },
                            },
                        },
                        scales: {
                            x: { title: { display: true, text: useHours ? 'Hours' : 'Minutes' }, beginAtZero: true },
                            y: { ticks: { font: { size: 11 } } },
                        },
                    };
                    return (
                        <>
                            <p className="text-xs text-gray-500 mb-3">Click a bar to see monthly trend</p>
                            <Bar data={dwellBarData} options={dwellBarOptions} />
                        </>
                    );
                })()}
            </div>

            {/* Activity Patterns */}
            <div className="bg-white rounded-2xl shadow-lg p-4 md:p-6 mt-4 md:mt-6">
                <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                    <h3 className="text-base md:text-xl font-bold text-gray-800">Activity Patterns</h3>
                    <div className="flex items-center gap-2">
                        <label className="text-xs text-gray-600 font-medium">Cat:</label>
                        <select
                            value={patternCat}
                            onChange={(e) => setPatternCat(e.target.value)}
                            className="p-1.5 text-sm border border-gray-300 rounded-lg shadow-sm"
                        >
                            {catNames.map(name => <option key={name} value={name}>{name}</option>)}
                        </select>
                    </div>
                </div>

                {/* Chart 1: 24-Hour Activity */}
                <div className="mb-8">
                    <h4 className="text-sm font-semibold text-gray-700 mb-1">24-Hour Activity Pattern</h4>
                    <p className="text-xs text-gray-500 mb-3">Fraction of days with outdoor activity each hour (last 90 days)</p>
                    {hourlyLoading ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading...</div>
                    ) : hourlyData.length === 0 ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No data available</div>
                    ) : (
                        <Bar
                            data={{
                                labels: hourlyData.map(d => `${d.hour}h`),
                                datasets: [{
                                    label: 'Fraction of days outside',
                                    data: hourlyData.map(d => d.outdoor_fraction),
                                    backgroundColor: '#38BDF8',
                                    borderRadius: 3,
                                }],
                            }}
                            options={{
                                responsive: true,
                                plugins: {
                                    legend: { display: false },
                                    tooltip: {
                                        callbacks: {
                                            label: (ctx) => `${(ctx.parsed.y * 100).toFixed(1)}% of days`,
                                        },
                                    },
                                },
                                scales: {
                                    y: {
                                        title: { display: true, text: 'Fraction of days' },
                                        beginAtZero: true,
                                        max: 1,
                                    },
                                    x: { title: { display: true, text: 'Hour of day' } },
                                },
                            }}
                        />
                    )}
                </div>

                {/* Chart 2: Seasonal Outdoor Hours */}
                <div className="mb-8">
                    <h4 className="text-sm font-semibold text-gray-700 mb-1">Seasonal Outdoor Hours</h4>
                    <p className="text-xs text-gray-500 mb-3">Daily outdoor hours — 7-day rolling average</p>
                    {seasonalLoading ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading...</div>
                    ) : seasonalData.length === 0 ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No data available</div>
                    ) : (() => {
                        const smoothed = seasonalData.map((d, i) => {
                            const window = seasonalData.slice(Math.max(0, i - 3), Math.min(seasonalData.length, i + 4));
                            return window.reduce((s, x) => s + x.outdoor_hours, 0) / window.length;
                        });
                        const lineColor = CAT_COLORS[patternCat] || '#3B82F6';
                        return (
                            <Line
                                data={{
                                    labels: seasonalData.map(d => d.date),
                                    datasets: [{
                                        label: 'Outdoor hours (7-day avg)',
                                        data: smoothed,
                                        borderColor: lineColor,
                                        backgroundColor: lineColor + '22',
                                        tension: 0.3,
                                        pointRadius: 0,
                                        borderWidth: 2,
                                    }],
                                }}
                                options={{
                                    responsive: true,
                                    plugins: {
                                        legend: { display: false },
                                        tooltip: {
                                            callbacks: {
                                                label: (ctx) => `${ctx.parsed.y.toFixed(2)}h`,
                                            },
                                        },
                                    },
                                    scales: {
                                        y: {
                                            title: { display: true, text: 'Hours per day' },
                                            beginAtZero: true,
                                        },
                                        x: {
                                            title: { display: true, text: 'Date' },
                                            ticks: {
                                                maxTicksLimit: 12,
                                                maxRotation: 45,
                                            },
                                        },
                                    },
                                }}
                            />
                        );
                    })()}
                </div>

                {/* Chart 3: Temperature vs Outdoor Hours */}
                <div>
                    <h4 className="text-sm font-semibold text-gray-700 mb-1">Temperature vs Outdoor Hours</h4>
                    <p className="text-xs text-gray-500 mb-3">Each dot = one day. Colour = weather type.</p>
                    {weatherCorrLoading ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading...</div>
                    ) : weatherCorrData.length === 0 ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No data available</div>
                    ) : (() => {
                        const weatherBucket = (code) => {
                            if (code <= 2) return { label: 'Clear', color: '#FBBF24' };
                            if (code <= 49) return { label: 'Cloudy', color: '#9CA3AF' };
                            if (code <= 79) return { label: 'Rain', color: '#60A5FA' };
                            return { label: 'Storm/Snow', color: '#1E3A8A' };
                        };
                        const bucketNames = ['Clear', 'Cloudy', 'Rain', 'Storm/Snow'];
                        const bucketColors = { Clear: '#FBBF24', Cloudy: '#9CA3AF', Rain: '#60A5FA', 'Storm/Snow': '#1E3A8A' };

                        const grouped = {};
                        bucketNames.forEach(b => { grouped[b] = []; });
                        weatherCorrData.forEach(d => {
                            const b = weatherBucket(d.weathercode);
                            grouped[b.label].push({ x: d.temp_max, y: d.outdoor_hours });
                        });

                        const datasets = bucketNames
                            .filter(b => grouped[b].length > 0)
                            .map(b => ({
                                label: b,
                                data: grouped[b],
                                backgroundColor: bucketColors[b] + 'CC',
                                pointRadius: 4,
                                pointHoverRadius: 6,
                            }));

                        return (
                            <Scatter
                                data={{ datasets }}
                                options={{
                                    responsive: true,
                                    plugins: {
                                        legend: { position: 'top' },
                                        tooltip: {
                                            callbacks: {
                                                label: (ctx) => `${ctx.parsed.x.toFixed(1)}°C, ${ctx.parsed.y.toFixed(2)}h`,
                                            },
                                        },
                                    },
                                    scales: {
                                        x: { title: { display: true, text: 'Max temperature (°C)' } },
                                        y: { title: { display: true, text: 'Outdoor hours' }, beginAtZero: true },
                                    },
                                }}
                            />
                        );
                    })()}
                </div>
            </div>

            {/* Zone Trend Modal */}
            {trendModalZone && (
                <div
                    style={{ position: 'fixed', inset: 0, zIndex: 1000, backgroundColor: 'rgba(0,0,0,0.5)' }}
                    onClick={() => setTrendModalZone(null)}
                >
                    <div
                        className="bg-white rounded-2xl shadow-2xl p-6 mx-auto mt-20"
                        style={{ maxWidth: 640, position: 'relative' }}
                        onClick={e => e.stopPropagation()}
                    >
                        <button
                            onClick={() => setTrendModalZone(null)}
                            className="absolute top-4 right-4 text-gray-500 hover:text-gray-800 text-xl font-bold leading-none"
                            aria-label="Close"
                        >
                            ×
                        </button>
                        <h3 className="text-lg font-bold text-gray-800 mb-1">{trendModalZone}</h3>
                        <p className="text-xs text-gray-500 mb-4">Monthly % of tracked time — {dwellCat}</p>
                        {trendModalLoading ? (
                            <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading...</div>
                        ) : trendModalData.length === 0 ? (
                            <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No monthly data available</div>
                        ) : (
                            <Line
                                data={{
                                    labels: trendModalData.map(d => d.month),
                                    datasets: [{
                                        label: '% of tracked time',
                                        data: trendModalData.map(d => d.pct_of_total),
                                        borderColor: '#3B82F6',
                                        backgroundColor: 'rgba(59,130,246,0.1)',
                                        tension: 0.3,
                                        pointRadius: 4,
                                    }],
                                }}
                                options={{
                                    responsive: true,
                                    plugins: {
                                        legend: { display: false },
                                        tooltip: {
                                            callbacks: { label: (ctx) => `${ctx.parsed.y}%` },
                                        },
                                    },
                                    scales: {
                                        y: { title: { display: true, text: '% of tracked time' }, beginAtZero: true },
                                        x: { title: { display: true, text: 'Month' } },
                                    },
                                }}
                            />
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default HistoryView;
