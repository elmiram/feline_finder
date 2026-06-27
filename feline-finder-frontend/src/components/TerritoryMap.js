import React, { useMemo, useEffect, useState } from 'react';
import { MapContainer, TileLayer, Polygon, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import '../map.css';

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

const TerritoryMap = ({ gpsPoints, zones, territory, viewType }) => {
    const [tileStyle, setTileStyle] = useState('map');

    const bounds = useMemo(() => {
        const coords = [
            ...gpsPoints.map(p => [p.lat, p.lon]),
            ...Object.values(zones).flat().map(p => [p[0], p[1]]),
            ...territory.map(p => [p[0], p[1]]),
        ];
        if (coords.length === 0) return null;
        const lats = coords.map(p => p[0]);
        const lons = coords.map(p => p[1]);
        return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
    }, [gpsPoints, zones, territory]);

    const sampledPoints = useMemo(() => downsample(gpsPoints, 600), [gpsPoints]);
    const zoneEntries = Object.entries(zones);
    const hasData = gpsPoints.length > 0 || zoneEntries.length > 0 || territory.length > 0;
    const isSatellite = tileStyle === 'satellite';
    const tile = TILE_LAYERS[tileStyle];

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

                {viewType === 'territory' && territory.length > 0 && (
                    <Polygon
                        positions={territory.map(p => [p[0], p[1]])}
                        pathOptions={{
                            fillColor: '#3B82F6',
                            fillOpacity: 0.2,
                            color: isSatellite ? '#60a5fa' : '#3B82F6',
                            weight: 2,
                        }}
                    />
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

            {!hasData && (
                <div className="absolute inset-0 flex items-center justify-center bg-gray-50 text-gray-500 text-sm">
                    No GPS data available for this window.
                </div>
            )}
        </div>
    );
};

export default TerritoryMap;
