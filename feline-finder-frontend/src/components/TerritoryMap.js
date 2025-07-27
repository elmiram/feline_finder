import React, {useRef, useEffect} from 'react';

const TerritoryMap = ({gpsPoints, zones, territory, viewType}) => {
    const canvasRef = useRef(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const allZonePoints = Object.values(zones).flat();
        const allPoints = [...gpsPoints.map(p => ({lat: p.lat, lon: p.lon})), ...allZonePoints.map(p => ({
            lat: p[0],
            lon: p[1]
        }))];

        if (allPoints.length === 0) {
            ctx.fillStyle = '#6B7280';
            ctx.textAlign = 'center';
            ctx.font = '16px sans-serif';
            ctx.fillText('No GPS data available for this window.', canvas.width / 2, canvas.height / 2);
            return;
        }

        // Hardcoded map boundaries for consistency, can be dynamic if needed
        const minLat = 47.162404, maxLat = 47.170737;
        const minLon = 8.618863, maxLon = 8.637247;
        const latRange = maxLat - minLat || 0.001, lonRange = maxLon - minLon || 0.001;
        const padding = 20;

        const toCanvasCoords = (lat, lon) => {
            const x = padding + ((lon - minLon) / lonRange) * (canvas.width - 2 * padding);
            const y = padding + ((maxLat - lat) / latRange) * (canvas.height - 2 * padding);
            return {x, y};
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
            ctx.font = 'bold 10px sans-serif';
            ctx.fillText(zoneName, labelPos.x, labelPos.y);

            colorIndex++;
        }

        // Draw GPS points or Territory
        if (viewType === 'points' && gpsPoints.length > 0) {
            gpsPoints.forEach((p, i) => {
                const {x, y} = toCanvasCoords(p.lat, p.lon);
                ctx.beginPath();
                ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
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
    }, [gpsPoints, zones, territory, viewType]);

    return (
        <div className="w-full h-[500px] rounded-lg overflow-hidden border">
            <canvas ref={canvasRef} className="bg-gray-50 w-full h-full"></canvas>
        </div>
    );
};

export default TerritoryMap;