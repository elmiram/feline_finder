import React, { useState, useEffect, useRef } from 'react';
import { Wifi, Battery, MapPin, AlertTriangle, PawPrint, Play, Square, Home, TreeDeciduous, Eye, User, Satellite, DoorOpen, RefreshCw } from 'lucide-react';

// --- Configuration ---
const API_BASE_URL = 'http://192.168.1.185:5000';

// --- Helper Functions ---
const formatRelativeTime = (date) => {
  if (!date) return 'N/A';
  const now = new Date();
  const seconds = Math.round((now - new Date(date)) / 1000);
  const minutes = Math.round(seconds / 60);
  const hours = Math.round(minutes / 60);
  const days = Math.round(hours / 24);

  if (seconds < 60) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (hours < 24) return `${hours} hr ago`;
  return `${days} day(s) ago`;
};

const formatDate = (date) => new Date(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

// --- Helper Components ---

const BatteryStatus = ({ level, isCharging }) => {
  if (level === null || typeof level === 'undefined') return null;
  let color = 'text-green-600';
  if (level <= 20) color = 'text-red-600';
  else if (level <= 50) color = 'text-yellow-600';
  const chargingColor = 'text-blue-600';
  return (
    <div className={`flex items-center space-x-1.5 text-sm font-medium ${isCharging ? chargingColor : color}`}>
      <Battery className="w-5 h-5" />
      <span>{level}%{isCharging ? ' (Charging)' : ''}</span>
    </div>
  );
};

const EventLog = ({ events }) => {
    if (!events || events.length === 0) {
        return <div className="text-center text-sm text-gray-400 py-4">No recent events</div>;
    }
    const getIcon = (e) => {
        const source = e.source ?? e.event_source;
        if (source === 0) return e.direction === 1 ? <Home className="w-4 h-4 text-blue-500"/> : <TreeDeciduous className="w-4 h-4 text-green-500"/>;
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
                    <li key={e.surepet_event_id} className="flex items-center justify-between text-sm p-2 bg-gray-50 rounded-md">
                        <span className="flex items-center gap-2 text-gray-700">{getIcon(e)} {getText(e)}</span>
                        <span className="text-gray-400" title={new Date(e.timestamp).toLocaleString()}>{formatRelativeTime(e.timestamp)}</span>
                    </li>
                ))}
            </ul>
        </div>
    );
};


const StatusCard = ({ cat, lastRefresh }) => {
  const getConfidenceColor = (c) => (c === 'High' ? 'bg-green-100 text-green-800' : c === 'Medium' ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800');
  const getStatusIcon = (s) => {
    const ls = s.toLowerCase();
    if (ls.includes('home')) return <Home className="w-6 h-6 text-blue-500" />;
    if (ls.includes('outside')) return <TreeDeciduous className="w-6 h-6 text-green-500" />;
    if (ls.includes('charging')) return <Battery className="w-6 h-6 text-yellow-500" />;
    return <AlertTriangle className="w-6 h-6 text-gray-500" />;
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg p-6 flex flex-col justify-between transform hover:scale-105 transition-transform duration-300">
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-3"><div className="bg-gray-100 p-3 rounded-full"><PawPrint className="w-6 h-6 text-gray-600" /></div><h2 className="text-2xl font-bold text-gray-800">{cat.name}</h2></div>
          <BatteryStatus level={cat.battery_level} isCharging={cat.is_charging} />
        </div>
        <div className="flex items-start space-x-3 my-4">
            {getStatusIcon(cat.status)}
            <div>
                <p className="text-xl font-semibold text-gray-700">{cat.status}</p>
                {cat.location_detail && (
                    <p className="text-sm text-blue-600 font-medium">{cat.location_detail}</p>
                )}
            </div>
        </div>
        <p className="text-gray-500 text-sm mb-4 h-10">{cat.evidence}</p>
      </div>
      <div className="border-t pt-4 mt-4">
        <div className="flex justify-between items-center mb-3">
            <span className={`px-3 py-1 text-sm font-semibold rounded-full ${getConfidenceColor(cat.confidence)}`}>Confidence: {cat.confidence}</span>
        </div>
        <div className="space-y-2 text-xs text-gray-500">
            <div className="flex items-center justify-between" title={cat.tractive_update_time ? new Date(cat.tractive_update_time).toLocaleString() : 'N/A'}>
                <span className="flex items-center gap-1.5"><Satellite className="w-3 h-3"/> Last tracker update:</span>
                <span>{formatRelativeTime(cat.tractive_update_time)}</span>
            </div>
            <div className="flex items-center justify-between" title={cat.surepet_update_time ? new Date(cat.surepet_update_time).toLocaleString() : 'N/A'}>
                <span className="flex items-center gap-1.5"><DoorOpen className="w-3 h-3"/> Last cat flap event:</span>
                <span>{formatRelativeTime(cat.surepet_update_time)}</span>
            </div>
            <div className="flex items-center justify-between" title={lastRefresh ? lastRefresh.toLocaleString() : 'N/A'}>
                <span className="flex items-center gap-1.5"><RefreshCw className="w-3 h-3"/> Dashboard refreshed:</span>
                <span>{formatRelativeTime(lastRefresh)}</span>
            </div>
        </div>
      </div>
    </div>
  );
};

const LoadingSpinner = () => (<div className="flex justify-center items-center h-64"><div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-blue-500"></div></div>);
const ErrorDisplay = ({ message }) => (<div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 rounded-lg" role="alert"><p className="font-bold">Error</p><p>{message}</p></div>);

// --- Main App Component ---

export default function App() {
  const [activeView, setActiveView] = useState('dashboard');
  
  // Dashboard State
  const [catsStatus, setCatsStatus] = useState({});
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshTime, setLastRefreshTime] = useState(null);
  const statusIntervalRef = useRef(null);

  // History State
  const [historyCat, setHistoryCat] = useState('');
  const [windowSizeDays, setWindowSizeDays] = useState(7);
  const [historyEndDate, setHistoryEndDate] = useState(new Date());
  
  const [fullHistoryGps, setFullHistoryGps] = useState([]);
  const [fullHistoryEvents, setFullHistoryEvents] = useState([]);
  const [territoryPolygon, setTerritoryPolygon] = useState([]);
  
  const [filteredGps, setFilteredGps] = useState([]);
  const [filteredEvents, setFilteredEvents] = useState([]);
  
  const [mapViewType, setMapViewType] = useState('points'); // 'points' or 'territory'

  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [knownZones, setKnownZones] = useState({});
  const timeChartRef = useRef(null);
  const isInitialCatLoad = useRef(true);

  const timelineStartDate = new Date(new Date().setDate(new Date().getDate() - 365));
  const historyStartDate = new Date(historyEndDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000);

  // Fetch Live Status and Zones on initial load
  useEffect(() => {
    const fetchInitialData = async () => {
      setStatusLoading(true);
      setStatusError(null);
      try {
        const [statusRes, zonesRes] = await Promise.all([
            fetch(`${API_BASE_URL}/api/status`),
            fetch(`${API_BASE_URL}/api/zones`)
        ]);
        if (!statusRes.ok) throw new Error(`HTTP error! status: ${statusRes.status}`);
        if (!zonesRes.ok) throw new Error(`HTTP error! status: ${zonesRes.status}`);
        
        const statusData = await statusRes.json();
        const zonesData = await zonesRes.json();

        setCatsStatus(statusData);
        setKnownZones(zonesData);
        setLastRefreshTime(new Date());
        if (!historyCat) setHistoryCat(Object.keys(statusData)[0] || '');

      } catch (e) {
        console.error("Failed to fetch initial data:", e);
        setStatusError("Could not connect to API server. Please ensure it is running and the IP address is correct.");
      } finally {
        setStatusLoading(false);
      }
    };
    fetchInitialData();
  }, []);


  // Handle Auto-Refresh
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/status`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        setCatsStatus(data);
        setLastRefreshTime(new Date());
      } catch (e) {
        console.error("Failed to fetch cat status:", e);
      }
    };
    if (statusIntervalRef.current) clearInterval(statusIntervalRef.current);
    if (autoRefresh) {
      statusIntervalRef.current = setInterval(fetchStatus, 30000);
    }
    return () => { if (statusIntervalRef.current) clearInterval(statusIntervalRef.current); };
  }, [autoRefresh]);
  
  // Set a flag when the cat changes to trigger the loading spinner
  useEffect(() => {
    isInitialCatLoad.current = true;
  }, [historyCat]);

  // Fetch History Data when controls change
  useEffect(() => {
    if (activeView !== 'history' || !historyCat) return;
    
    const fetchHistoryForWindow = async () => {
      if (isInitialCatLoad.current) {
        setHistoryLoading(true);
      }
      setHistoryError(null);
      
      const endDate = historyEndDate;
      const startDate = new Date(endDate.getTime() - windowSizeDays * 24 * 60 * 60 * 1000);

      try {
        const [gpsRes, eventsRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/history/gps?cat_name=${historyCat}&start_date=${startDate.toISOString()}&end_date=${endDate.toISOString()}`),
          fetch(`${API_BASE_URL}/api/history/events?cat_name=${historyCat}&start_date=${startDate.toISOString()}&end_date=${endDate.toISOString()}`)
        ]);
        if (!gpsRes.ok || !eventsRes.ok) throw new Error('Failed to fetch history data');
        const gpsData = await gpsRes.json();
        const eventsData = await eventsRes.json();
        
        setFilteredGps(gpsData.positions.map(p => ({...p, time: new Date(p.time)})));
        setTerritoryPolygon(gpsData.territory_polygon);
        setFilteredEvents(eventsData.map(e => ({...e, time: new Date(e.time)})));

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
  }, [activeView, historyCat, windowSizeDays, historyEndDate]);
  

  // Render Visualizations
  useEffect(() => {
    if (activeView === 'history' && !historyLoading) {
      renderMap(filteredGps, knownZones, territoryPolygon, mapViewType);
      renderTimeChart(filteredEvents, windowSizeDays, historyEndDate);
    }
  }, [filteredGps, filteredEvents, territoryPolygon, historyLoading, knownZones, mapViewType]);

  const renderMap = (gpsPoints, zones, territory, viewType) => {
    const canvas = document.getElementById('map-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const allZonePoints = Object.values(zones).flat();
    const allPoints = [...gpsPoints.map(p => ({lat: p.lat, lon: p.lon})), ...allZonePoints.map(p => ({lat: p[0], lon: p[1]}))];
    
    if (allPoints.length === 0) {
      ctx.fillStyle = '#6B7280'; ctx.textAlign = 'center'; ctx.font = '16px Inter';
      ctx.fillText('No GPS data available for this window.', canvas.width / 2, canvas.height / 2);
      return;
    }

    const lats = allPoints.map(p => p.lat), lons = allPoints.map(p => p.lon);
    // We can decide the map border based on the incoming data by finding min and max lat and long.
    // const minLat = Math.min(...lats), maxLat = Math.max(...lats);
    // const minLon = Math.min(...lons), maxLon = Math.max(...lons);
    // Alternatively we can set the map border manually.
    const minLat = 47.162404, maxLat = 47.170737;
    const minLon = 8.618863, maxLon = 8.637247;
    const latRange = maxLat - minLat || 0.001, lonRange = maxLon - minLon || 0.001;
    const padding = 20;

    const toCanvasCoords = (lat, lon) => {
        const x = padding + ((lon - minLon) / lonRange) * (canvas.width - 2 * padding);
        const y = padding + ((maxLat - lat) / latRange) * (canvas.height - 2 * padding);
        return { x, y };
    };

    // Draw Zones
    const zoneColors = ['rgba(107, 138, 122, 0.2)', 'rgba(142, 124, 104, 0.2)', 'rgba(204, 153, 102, 0.2)', 'rgba(153, 102, 102, 0.2)'];
    let colorIndex = 0;
    for (const zoneName in zones) {
        const polygon = zones[zoneName];
        ctx.beginPath();
        const startPoint = toCanvasCoords(polygon[0][0], polygon[0][1]);
        ctx.moveTo(startPoint.x, startPoint.y);
        for (let i = 1; i < polygon.length; i++) {
            const point = toCanvasCoords(polygon[i][0], polygon[i][1]);
            ctx.lineTo(point.x, point.y);
        }
        ctx.closePath();
        ctx.fillStyle = zoneColors[colorIndex % zoneColors.length];
        ctx.fill();
        ctx.strokeStyle = zoneColors[colorIndex % zoneColors.length].replace('0.2', '0.5');
        ctx.stroke();
        
        const center = polygon.reduce((acc, p) => ({lat: acc.lat + p[0], lon: acc.lon + p[1]}), {lat: 0, lon: 0});
        center.lat /= polygon.length;
        center.lon /= polygon.length;
        const labelPos = toCanvasCoords(center.lat, center.lon);
        ctx.fillStyle = '#374151';
        ctx.textAlign = 'center';
        ctx.font = 'bold 10px Inter';
        ctx.fillText(zoneName, labelPos.x, labelPos.y);

        colorIndex++;
    }

    // Draw GPS points or Territory
    if (viewType === 'points' && gpsPoints.length > 0) {
        gpsPoints.forEach((p, i) => {
          const { x, y } = toCanvasCoords(p.lat, p.lon);
          ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
          ctx.fillStyle = `rgba(59, 130, 246, ${0.3 + (i / gpsPoints.length) * 0.7})`;
          ctx.fill();
        });
    } else if (viewType === 'territory' && territory.length > 0) {
        ctx.beginPath();
        const startPoint = toCanvasCoords(territory[0][0], territory[0][1]);
        ctx.moveTo(startPoint.x, startPoint.y);
        for (let i = 1; i < territory.length; i++) {
            const point = toCanvasCoords(territory[i][0], territory[i][1]);
            ctx.lineTo(point.x, point.y);
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(59, 130, 246, 0.2)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(59, 130, 246, 0.8)';
        ctx.lineWidth = 2;
        ctx.stroke();
    }
  };

  const renderTimeChart = (events, days, endDate) => {
    if (typeof window.Chart === 'undefined') return;
    const canvas = document.getElementById('time-chart');
    if (!canvas) return;
    if (timeChartRef.current) timeChartRef.current.destroy();
    let insideTime = 0, outsideTime = 0;
    if (events.length > 0) {
        let lastStatus = events[0].direction;
        let lastTime = new Date(endDate.getTime() - days * 24 * 60 * 60 * 1000);
        [...events, {time: endDate, direction: events[events.length-1].direction, source: -1}].forEach(event => {
            const currentTime = new Date(event.time);
            const duration = (currentTime - lastTime) / (1000 * 3600);
            if(lastStatus === 1) insideTime += duration; else outsideTime += duration;
            if (event.source === 0 || event.source === 1) lastStatus = event.direction;
            lastTime = currentTime;
        });
    }
    const total = insideTime + outsideTime;
    const insidePercent = total > 0 ? Math.round((insideTime / total) * 100) : 50;
    
    timeChartRef.current = new window.Chart(canvas, {
      type: 'doughnut', data: { labels: ['Inside', 'Outside'], datasets: [{ data: [insidePercent, 100 - insidePercent], backgroundColor: ['#6B8A7A', '#8E7C68'], borderColor: '#FFFFFF', borderWidth: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '70%', plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => `${c.label}: ${c.raw}%` } } } }
    });
  };

  return (
    <div className="bg-gray-50 min-h-screen font-sans p-4 sm:p-6 lg:p-8">
      <div className="max-w-6xl mx-auto">
        <header className="mb-8 text-center">
          <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-800 tracking-tight">FelineFinder Dashboard</h1>
          <p className="mt-2 text-lg text-gray-500">Cat tracking and behavior analysis</p>
        </header>
        
        <div className="mb-8 border-b border-gray-200"><nav className="flex -mb-px space-x-6">
            <button onClick={() => setActiveView('dashboard')} className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-lg ${activeView === 'dashboard' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>Live Dashboard</button>
            <button onClick={() => setActiveView('history')} className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-lg ${activeView === 'history' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>Historical Analysis</button>
        </nav></div>

        {activeView === 'dashboard' && (
            <div>
                <div className="flex justify-center items-center space-x-4 mb-8">
                    {autoRefresh ? (
                        <button onClick={() => setAutoRefresh(false)} className="flex items-center space-x-2 px-4 py-2 bg-red-500 text-white rounded-lg shadow-md hover:bg-red-600 transition-colors"><Square className="w-5 h-5" /><span>Stop Auto-Refresh</span></button>
                    ) : (
                        <button onClick={() => setAutoRefresh(true)} className="flex items-center space-x-2 px-4 py-2 bg-green-500 text-white rounded-lg shadow-md hover:bg-green-600 transition-colors"><Play className="w-5 h-5" /><span>Start Auto-Refresh</span></button>
                    )}
                </div>
                {statusLoading ? <LoadingSpinner /> : statusError ? <ErrorDisplay message={statusError} /> : (
                    <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-8">
                        {Object.values(catsStatus).map(cat => (
                            <div key={cat.name} className="flex flex-col gap-8">
                                <StatusCard cat={cat} lastRefresh={lastRefreshTime} />
                                <div className="bg-white rounded-2xl shadow-lg p-6">
                                    <EventLog events={cat.recent_events} />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        )}

        {activeView === 'history' && (
            <div>
                <div className="bg-white rounded-2xl shadow-lg p-6 mb-8">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                        <div><label htmlFor="cat-select" className="block text-sm font-medium text-gray-700 mb-1">Select Cat</label><select id="cat-select" value={historyCat} onChange={(e) => setHistoryCat(e.target.value)} className="w-full p-2 border border-gray-300 rounded-lg shadow-sm">{Object.keys(catsStatus).map(name => <option key={name} value={name}>{name}</option>)}</select></div>
                        <div><label htmlFor="window-select" className="block text-sm font-medium text-gray-700 mb-1">Window Size</label><select id="window-select" value={windowSizeDays} onChange={(e) => setWindowSizeDays(Number(e.target.value))} className="w-full p-2 border border-gray-300 rounded-lg shadow-sm"><option value="7">7 Days</option><option value="14">14 Days</option><option value="30">30 Days</option></select></div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Map View</label>
                            <div className="flex items-center space-x-2 bg-gray-100 p-1 rounded-lg">
                                <button onClick={() => setMapViewType('points')} className={`w-full py-1 text-sm rounded-md ${mapViewType === 'points' ? 'bg-white shadow' : 'text-gray-600'}`}>Points</button>
                                <button onClick={() => setMapViewType('territory')} className={`w-full py-1 text-sm rounded-md ${mapViewType === 'territory' ? 'bg-white shadow' : 'text-gray-600'}`}>Territory</button>
                            </div>
                        </div>
                    </div>
                    <div>
                        <label htmlFor="timeline-slider" className="block text-sm font-medium text-gray-700 mb-2">Timeline</label>
                        <input type="range" id="timeline-slider" min={timelineStartDate.getTime()} max={new Date().getTime()} value={historyEndDate.getTime()} onChange={(e) => setHistoryEndDate(new Date(Number(e.target.value)))} step={86400000} className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                        <div className="flex justify-between text-xs text-gray-500 mt-2">
                            <span>{formatDate(historyStartDate)}</span>
                            <span>{formatDate(historyEndDate)}</span>
                        </div>
                    </div>
                </div>
                {historyLoading ? <LoadingSpinner /> : historyError ? <ErrorDisplay message={historyError} /> : (
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        <div className="lg:col-span-3 bg-white rounded-2xl shadow-lg p-6">
                            <h3 className="text-xl font-bold text-gray-800 mb-4">Territory Map</h3>
                            <div className="w-full rounded-lg overflow-hidden border">
                                <canvas id="map-canvas" className="bg-gray-50 w-full h-full"></canvas>
                            </div>
                        </div>
                        {/*
                        <div className="bg-white rounded-2xl shadow-lg p-6">
                            <h3 className="text-xl font-bold text-gray-800 mb-4">Time Allocation</h3>
                            <div className="chart-container h-48 max-h-48 w-full max-w-xs mx-auto">
                                <canvas id="time-chart"></canvas>
                            </div>
                        </div>
                        */}
                    </div>
                )}
            </div>
        )}
      </div>
    </div>
  );
}
