import React, { useMemo, useEffect, useState } from 'react';
import L from 'leaflet';
import 'leaflet.heat';
import { MapContainer, TileLayer, Polygon, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import '../map.css';
import { API_BASE_URL } from '../constants';

const ZONE_COLORS = [
    { fill: '#6B8A7A', stroke: '#4a6b5a' },
    { fill: '#8E7C68', stroke: '#6e5c48' },
    { fill: '#CC9966', stroke: '#aa7744' },
    { fill: '#996666', stroke: '#774444' },
];

const TILE_LAYERS = {
    map: {
        url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        label: 'Map',
    },
    satellite: {
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attribution: '&copy; <a href="https://www.esri.com/">Esri</a> World Imagery',
        label: 'Satellite',
    },
    topo: {
        url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
        label: 'Topo',
    },
};

const DEFAULT_CENTER = [47.1666, 8.6280];
const DEFAULT_ZOOM = 15;

const downsample = (points, maxCount) => {
    if (points.length <= maxCount) return points;
    const step = Math.ceil(points.length / maxCount);
    const result = [];
    for (let i = 0; i < points.length; i += step) result.push(points[i]);
    if (result[result.length - 1] !== points[points.length - 1]) result.push(points[points.length - 1]);
    return result;
};

const FitBounds = ({ bounds }) => {
    const map = useMap();
    useEffect(() => {
        if (bounds) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 17 });
    }, [map, bounds]);
    return null;
};

function HeatmapLayer({ points }) {
    const map = useMap();
    useEffect(() => {
        if (!points.length) return;
        const heat = L.heatLayer(points, { radius: 25, blur: 15, maxZoom: 17 });
        heat.addTo(map);
        return () => heat.remove();
    }, [map, points]);
    return null;
}

// Find the best-matching weekly territory entry for the selected date
const findTerritoryForDate = (territories, selectedDate) => {
    if (!territories || territories.length === 0) return null;
    const selected = selectedDate instanceof Date ? selectedDate : new Date(selectedDate);
    const selectedTs = selected.getTime();

    // Find exact match: period_start <= selectedDate <= period_end
    const exact = territories.find(t => {
        const start = new Date(t.period_start).getTime();
        const end = new Date(t.period_end).getTime();
        return start <= selectedTs && selectedTs <= end;
    });
    if (exact) return exact;

    // Fallback: closest by period_start
    let closest = null;
    let minDiff = Infinity;
    for (const t of territories) {
        const diff = Math.abs(new Date(t.period_start).getTime() - selectedTs);
        if (diff < minDiff) {
            minDiff = diff;
            closest = t;
        }
    }
    return closest;
};

// Convert [lon, lat] stored coords to Leaflet [lat, lon]
const swapCoords = (ring) => ring.map(([lon, lat]) => [lat, lon]);

// Parse a territory DB entry into Leaflet positions array (outer ring + holes), or null
const parsePositions = (entry) => {
    if (!entry) return null;
    try {
        const outerRing = swapCoords(JSON.parse(entry.polygon_json));
        const holesRaw = entry.holes_json ? JSON.parse(entry.holes_json) : null;
        const holes = holesRaw ? holesRaw.map(swapCoords) : [];
        return [outerRing, ...holes];
    } catch (e) {
        console.error('Failed to parse territory polygon:', e);
        return null;
    }
};

const TerritoryMap = ({
    gpsPoints,
    zones,
    territory,
    viewType,
    catName,
    historyEndDate,
    historyStartDate,
    // All-cats mode props (optional)
    allCatsTerritories,
    allCatsLoading,
    catColors,
}) => {
    const [tileStyle, setTileStyle] = useState('map');

    // Single-cat alpha shape territory from DB
    const [weeklyTerritories, setWeeklyTerritories] = useState([]);
    const [territoryLoading, setTerritoryLoading] = useState(false);
    const [territoryFetched, setTerritoryFetched] = useState(null); // track which cat was fetched

    // Heatmap state
    const [heatmapCells, setHeatmapCells] = useState([]);
    const [heatmapMaxCount, setHeatmapMaxCount] = useState(1);
    const [heatmapLoading, setHeatmapLoading] = useState(false);

    const isAllCatsMode = !!allCatsTerritories;

    useEffect(() => {
        if (isAllCatsMode) return; // all-cats mode: HistoryView manages fetching
        if (viewType !== 'territory' || !catName) return;
        if (territoryFetched === catName) return; // already fetched for this cat

        setTerritoryLoading(true);
        fetch(`${API_BASE_URL}/api/territory/weekly?cat_name=${encodeURIComponent(catName)}&limit=52`)
            .then(r => r.json())
            .then(data => {
                setWeeklyTerritories(data.territories || []);
                setTerritoryFetched(catName);
            })
            .catch(err => {
                console.error('Failed to fetch weekly territories:', err);
                setWeeklyTerritories([]);
                setTerritoryFetched(catName);
            })
            .finally(() => setTerritoryLoading(false));
    }, [viewType, catName, territoryFetched, isAllCatsMode]);

    // Re-fetch when cat changes
    useEffect(() => {
        setTerritoryFetched(null);
        setWeeklyTerritories([]);
        setHeatmapCells([]);
    }, [catName]);

    // Fetch heatmap data when viewType is 'heatmap'
    useEffect(() => {
        if (viewType !== 'heatmap' || !catName) return;
        setHeatmapLoading(true);
        const end = historyEndDate instanceof Date ? historyEndDate : new Date(historyEndDate || Date.now());
        const start = historyStartDate instanceof Date
            ? historyStartDate
            : new Date(end.getTime() - 90 * 24 * 60 * 60 * 1000);
        fetch(
            `${API_BASE_URL}/api/history/heatmap?cat_name=${encodeURIComponent(catName)}&start_date=${start.toISOString()}&end_date=${end.toISOString()}`
        )
            .then(r => r.json())
            .then(data => {
                setHeatmapCells(data.cells || []);
                setHeatmapMaxCount(data.max_count || 1);
            })
            .catch(err => {
                console.error('Failed to fetch heatmap data:', err);
                setHeatmapCells([]);
            })
            .finally(() => setHeatmapLoading(false));
    }, [viewType, catName, historyEndDate, historyStartDate]);

    // Single-cat territory positions
    const alphaShapeEntry = useMemo(() => {
        if (isAllCatsMode || viewType !== 'territory') return null;
        return findTerritoryForDate(weeklyTerritories, historyEndDate || new Date());
    }, [weeklyTerritories, historyEndDate, viewType, isAllCatsMode]);

    const alphaPositions = useMemo(() => parsePositions(alphaShapeEntry), [alphaShapeEntry]);

    // All-cats territory positions: array of { catName, color, positions }
    const allCatsPolygons = useMemo(() => {
        if (!isAllCatsMode || !allCatsTerritories) return [];
        const selectedDate = historyEndDate || new Date();
        return Object.entries(allCatsTerritories).flatMap(([name, territories]) => {
            const entry = findTerritoryForDate(territories, selectedDate);
            const positions = parsePositions(entry);
            if (!positions) return [];
            return [{ catName: name, color: (catColors && catColors[name]) || '#999999', positions }];
        });
    }, [isAllCatsMode, allCatsTerritories, historyEndDate, catColors]);

    const heatPoints = useMemo(() => {
        if (viewType !== 'heatmap') return [];
        return heatmapCells.map(c => [c.lat, c.lon, c.count / (heatmapMaxCount || 1)]);
    }, [heatmapCells, heatmapMaxCount, viewType]);

    const bounds = useMemo(() => {
        let coords = [
            ...gpsPoints.map(p => [p.lat, p.lon]),
            ...Object.values(zones).flat().map(p => [p[0], p[1]]),
        ];

        if (isAllCatsMode) {
            allCatsPolygons.forEach(({ positions }) => {
                coords = [...coords, ...positions.flat()];
            });
        } else if (viewType === 'territory' && alphaPositions) {
            coords = [...coords, ...alphaPositions.flat()];
        } else {
            coords = [...coords, ...territory.map(p => [p[0], p[1]])];
        }

        if (coords.length === 0) return null;
        const lats = coords.map(p => p[0]);
        const lons = coords.map(p => p[1]);
        return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
    }, [gpsPoints, zones, territory, alphaPositions, viewType, isAllCatsMode, allCatsPolygons]);

    const sampledPoints = useMemo(() => downsample(gpsPoints, 600), [gpsPoints]);
    const zoneEntries = Object.entries(zones);
    const hasData = gpsPoints.length > 0 || zoneEntries.length > 0 || territory.length > 0
        || alphaPositions !== null || heatmapCells.length > 0 || allCatsPolygons.length > 0;
    const isSatellite = tileStyle === 'satellite';
    const tile = TILE_LAYERS[tileStyle];

    const noTerritoryForPeriod = !isAllCatsMode && viewType === 'territory' && !territoryLoading && weeklyTerritories.length > 0 && !alphaShapeEntry;
    const noTerritoryAtAll = !isAllCatsMode && viewType === 'territory' && !territoryLoading && weeklyTerritories.length === 0 && territoryFetched === catName;

    const isLoading = territoryLoading || heatmapLoading || (isAllCatsMode && allCatsLoading);

    return (
        <div className="w-full rounded-lg overflow-hidden border relative" style={{ height: 'clamp(280px, 45vh, 500px)' }}>
            <MapContainer
                center={DEFAULT_CENTER}
                zoom={DEFAULT_ZOOM}
                style={{ height: '100%', width: '100%' }}
                zoomControl={true}
            >
                <TileLayer key={tileStyle} url={tile.url} attribution={tile.attribution} />

                {bounds && <FitBounds bounds={bounds} />}

                {zoneEntries.map(([name, polygon], i) => {
                    const color = ZONE_COLORS[i % ZONE_COLORS.length];
                    return (
                        <Polygon
                            key={name}
                            positions={polygon.map(p => [p[0], p[1]])}
                            pathOptions={{
                                fillColor: color.fill,
                                fillOpacity: isSatellite ? 0.1 : 0.2,
                                color: isSatellite ? '#ffffff' : color.stroke,
                                weight: isSatellite ? 2.5 : 2,
                            }}
                        >
                            <Tooltip direction="center" className="zone-label" sticky>{name}</Tooltip>
                        </Polygon>
                    );
                })}

                {viewType === 'points' && sampledPoints.map((p, i) => (
                    <CircleMarker
                        key={i}
                        center={[p.lat, p.lon]}
                        radius={3}
                        pathOptions={{
                            fillColor: '#3B82F6',
                            fillOpacity: 0.3 + (i / sampledPoints.length) * 0.7,
                            color: 'transparent',
                            weight: 0,
                        }}
                    />
                ))}

                {/* Single-cat territory polygon */}
                {!isAllCatsMode && viewType === 'territory' && alphaPositions && (
                    <Polygon
                        positions={alphaPositions}
                        pathOptions={{
                            fillColor: '#3B82F6',
                            fillOpacity: 0.2,
                            color: isSatellite ? '#60a5fa' : '#3B82F6',
                            weight: 2,
                        }}
                    />
                )}

                {/* All-cats territory polygons */}
                {isAllCatsMode && allCatsPolygons.map(({ catName: name, color, positions }) => (
                    <Polygon
                        key={name}
                        positions={positions}
                        pathOptions={{
                            fillColor: color,
                            fillOpacity: 0.2,
                            color: color,
                            weight: 2,
                        }}
                    />
                ))}

                {viewType === 'heatmap' && heatPoints.length > 0 && (
                    <HeatmapLayer points={heatPoints} />
                )}
            </MapContainer>

            {/* Tile layer toggle — top-right corner, above Leaflet controls */}
            <div className="absolute top-2 right-2 flex rounded-lg overflow-hidden shadow border border-gray-300" style={{ zIndex: 1001 }}>
                {Object.entries(TILE_LAYERS).map(([key, layer]) => (
                    <button
                        key={key}
                        onClick={() => setTileStyle(key)}
                        className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                            tileStyle === key
                                ? 'bg-blue-600 text-white'
                                : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                    >
                        {layer.label}
                    </button>
                ))}
            </div>

            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-white bg-opacity-70 text-gray-500 text-sm" style={{ zIndex: 1002 }}>
                    Loading territory data...
                </div>
            )}

            {(noTerritoryForPeriod || noTerritoryAtAll) && (
                <div className="absolute inset-0 flex items-center justify-center bg-gray-50 bg-opacity-80 text-gray-500 text-sm" style={{ zIndex: 1002 }}>
                    No territory data for this period
                </div>
            )}

            {!hasData && !isLoading && viewType !== 'territory' && viewType !== 'heatmap' && (
                <div className="absolute inset-0 flex items-center justify-center bg-gray-50 text-gray-500 text-sm">
                    No GPS data available for this window.
                </div>
            )}
        </div>
    );
};

export default TerritoryMap;
