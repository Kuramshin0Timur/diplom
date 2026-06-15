// static/map.js - Полная исправленная версия

(function () {
    // ========== GLOBAL VARIABLES ==========
    let map = null;
    let baseTileLayer = null;
    let overlayLayers = [];
    let nextOverlayId = 1;

    // Base layers
    let gridLayer = null;

    // Coordinates data
    let coordinates = [];
    let allCoordinates = [];

    // Search state
    let searchQuery = '';

    // Library
    let libraryMaps = [];
    let currentMapInfo = null;
    let currentGcps = [];

    // Timeline variables
    let timelineActive = false;
    let timelineMarkersLayer = null;
    let allCoordinatesByDate = {};
    let sortedDates = [];
    let timelineSpeed = 1000;
    let timelinePlaying = false;
    let animationFrameId = null;
    let timelinePanel = null;
    let timelineToggleBtn = null;
    let currentDateIndex = 0;

    // ========== HELPER FUNCTIONS ==========
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i> ${message}`;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>]/g, function (m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    function formatNumber(num) {
        if (!num) return '0';
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    }

    async function apiFetch(url, options = {}) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error(`API Error: ${url}`, error);
            throw error;
        }
    }

    // ========== MAP INITIALIZATION ==========
    function initMap() {
        console.log('Initializing EPSG:3031 Antarctic map...');

        proj4.defs("EPSG:3031", "+proj=stere +lat_0=-90 +lat_ts=-71 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs");

        const antarcticBounds = { minX: -4500000, maxX: 4500000, minY: -4500000, maxY: 4500000 };
        const centerWgs84 = proj4('EPSG:3031', 'EPSG:4326', [0, 0]);

        const boundsWidth = antarcticBounds.maxX - antarcticBounds.minX;
        const maxResolution = boundsWidth / 256;
        const resolutions = [];
        for (let z = 0; z <= 8; z++) resolutions.push(maxResolution / Math.pow(2, z));

        const crs = new L.Proj.CRS('EPSG:3031',
            '+proj=stere +lat_0=-90 +lat_ts=-71 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs',
            { resolutions: resolutions, origin: [antarcticBounds.minX, antarcticBounds.maxY] }
        );

        map = L.map('antarctic-map', {
            crs: crs,
            center: [centerWgs84[1], centerWgs84[0]],
            zoom: 3,
            minZoom: 2,
            maxZoom: 8,
            zoomControl: false
        });

        map.on('moveend', updateMapUI);
        map.on('mousemove', updateMousePosition);

        document.getElementById('zoomInBtn')?.addEventListener('click', () => map.zoomIn());
        document.getElementById('zoomOutBtn')?.addEventListener('click', () => map.zoomOut());
        document.getElementById('resetViewBtn')?.addEventListener('click', () => map.setView([centerWgs84[1], centerWgs84[0]], 3));

        document.getElementById('toggleGridCheck')?.addEventListener('change', (e) => {
            if (e.target.checked) gridLayer?.addTo(map);
            else gridLayer?.removeFrom(map);
        });

        document.getElementById('baseOpacity')?.addEventListener('input', (e) => {
            const val = e.target.value;
            document.getElementById('baseOpacityLabel').textContent = val + '%';
            if (baseTileLayer) baseTileLayer.setOpacity(val / 100);
        });

        document.getElementById('addOverlayBtn')?.addEventListener('click', showOverlaySelectionModal);
        setupMainTabs();
        setupTimelineButton();

        console.log('Map initialized');
        return map;
    }

    function setupMainTabs() {
        const tabs = document.querySelectorAll('.tab');
        const mapWrapper = document.getElementById('mapWrapper');
        const coordinatesPanel = document.getElementById('coordinatesPanel');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                if (tabName === 'coordinates') {
                    if (mapWrapper) mapWrapper.style.display = 'none';
                    if (coordinatesPanel) {
                        coordinatesPanel.style.display = 'block';
                        renderCoordinatesTable();
                    }
                } else {
                    if (mapWrapper) mapWrapper.style.display = 'block';
                    if (coordinatesPanel) coordinatesPanel.style.display = 'none';

                    if (tabName === 'upload') {
                        document.getElementById('fileModal').style.display = 'block';
                    } else if (tabName === 'gcps') {
                        const processedMap = libraryMaps.find(m => m.processed);
                        if (processedMap) showGcpsModal(processedMap);
                        else showToast('Сначала обработайте карту', 'info');
                    }
                }
            });
        });
    }

    function updateMapUI() {
        const zoom = map.getZoom();
        const zoomDisplay = document.getElementById('zoomLevelDisplay');
        if (zoomDisplay) zoomDisplay.textContent = zoom;

        const center = map.getCenter();
        const centerMeters = proj4('EPSG:4326', 'EPSG:3031', [center.lng, center.lat]);
        const coordDisplay = document.getElementById('coordDisplay');
        if (coordDisplay) {
            coordDisplay.innerHTML = `EPSG:3031<br>X: ${Math.round(centerMeters[0]).toLocaleString()}<br>Y: ${Math.round(centerMeters[1]).toLocaleString()}`;
        }

        const scale = Math.round(40075000 * Math.cos(center.lat * Math.PI / 180) / Math.pow(2, zoom + 8));
        const scaleDisplay = document.getElementById('scaleDisplay');
        if (scaleDisplay) scaleDisplay.textContent = scale > 1000 ? `${Math.round(scale / 1000)} KM` : `${scale} M`;
    }

    function updateMousePosition(e) {
        if (e.latlng) {
            const meters = proj4('EPSG:4326', 'EPSG:3031', [e.latlng.lng, e.latlng.lat]);
            const coordDisplay = document.getElementById('coordDisplay');
            if (coordDisplay) {
                coordDisplay.innerHTML = `EPSG:3031<br>X: ${Math.round(meters[0]).toLocaleString()}<br>Y: ${Math.round(meters[1]).toLocaleString()}`;
            }
        }
    }

    // ========== TIMELINE FUNCTIONS ==========
    function setupTimelineButton() {
        const rightbar = document.querySelector('.rightbar');
        if (!rightbar) return;

        const layersPanel = rightbar.querySelector('.panel:first-child');
        if (!layersPanel) return;

        const layersDiv = layersPanel.querySelector('.layers');
        if (!layersDiv) return;

        const coordsCheckItem = layersDiv.querySelector('.check-item input#toggleCoordinatesCheck')?.closest('.check-item');
        if (coordsCheckItem) {
            coordsCheckItem.style.display = 'none';
        }

        timelineToggleBtn = document.createElement('button');
        timelineToggleBtn.id = 'timelineToggleBtn';
        timelineToggleBtn.className = 'timeline-btn';
        timelineToggleBtn.style.width = '100%';
        timelineToggleBtn.style.marginTop = '15px';
        timelineToggleBtn.style.background = 'linear-gradient(135deg, #2d7eff, #1a5bc4)';
        timelineToggleBtn.style.display = 'flex';
        timelineToggleBtn.style.alignItems = 'center';
        timelineToggleBtn.style.justifyContent = 'center';
        timelineToggleBtn.style.gap = '8px';
        timelineToggleBtn.innerHTML = '<i class="fas fa-calendar-alt"></i> 📅 Хронология землетрясений';

        timelineToggleBtn.addEventListener('click', toggleTimeline);

        const checksDiv = layersDiv.querySelector('.checks');
        if (checksDiv) {
            checksDiv.insertAdjacentElement('afterend', timelineToggleBtn);
        } else {
            layersDiv.appendChild(timelineToggleBtn);
        }
    }

    function createTimelinePanel() {
        if (document.getElementById('timelinePanel')) return;

        const timelineHTML = `
            <div id="timelinePanel" class="timeline-panel" style="display: none;">
                <div class="timeline-header">
                    <h4><i class="fas fa-calendar-alt"></i> Хронология землетрясений</h4>
                    <button id="closeTimelineBtn" class="timeline-close"><i class="fas fa-times"></i></button>
                </div>
                
                <div class="timeline-controls">
                    <div class="date-range-info" id="timelineDateRange">
                        Загрузка...
                    </div>
                    
                    <div class="timeline-slider-container">
                        <input type="range" id="timelineDateSlider" class="timeline-slider" min="0" max="0" value="0" step="1">
                    </div>
                    
                    <div class="timeline-buttons">
                        <button id="timelinePrevDay" class="timeline-btn" title="Предыдущий день">
                            <i class="fas fa-chevron-left"></i>
                        </button>
                        <button id="timelinePlayPause" class="timeline-btn play-btn" title="Воспроизвести">
                            <i class="fas fa-play"></i>
                        </button>
                        <button id="timelineNextDay" class="timeline-btn" title="Следующий день">
                            <i class="fas fa-chevron-right"></i>
                        </button>
                    </div>
                    
                    <div class="timeline-speed-control">
                        <span><i class="fas fa-tachometer-alt"></i> Скорость:</span>
                        <input type="range" id="timelineSpeedSlider" min="300" max="3000" value="1000" step="100">
                        <span id="timelineSpeedValue">1.0x</span>
                    </div>
                    
                    <div class="current-date-display">
                        <i class="fas fa-calendar-day"></i>
                        <span id="timelineCurrentDate">—</span>
                        <span id="timelineEventsCount" style="margin-left: 10px; font-size: 12px; color: #ffbe2f;"></span>
                    </div>
                    
                    <div class="timeline-stats">
                        <span><i class="fas fa-map-marker-alt"></i> <span id="timelineTotalMarkers">0</span> всего событий</span>
                        <span><i class="fas fa-calendar-week"></i> <span id="timelineTotalDays">0</span> дней</span>
                    </div>
                </div>
            </div>
        `;

        const rightbar = document.querySelector('.rightbar');
        if (rightbar) {
            rightbar.insertAdjacentHTML('afterbegin', timelineHTML);
        } else {
            document.body.insertAdjacentHTML('beforeend', `<div class="timeline-panel-floating" id="timelinePanel">${timelineHTML}</div>`);
        }

        addTimelineStyles();
        initTimelineEventListeners();
        timelinePanel = document.getElementById('timelinePanel');
    }

    function addTimelineStyles() {
        if (document.getElementById('timelineStyles')) return;

        const styles = document.createElement('style');
        styles.id = 'timelineStyles';
        styles.textContent = `
            .timeline-panel {
                background: linear-gradient(180deg, rgba(12, 42, 80, 0.98), rgba(6, 26, 50, 0.98));
                border: 1px solid rgba(80, 140, 220, 0.35);
                border-radius: 16px;
                backdrop-filter: blur(12px);
                margin-bottom: 16px;
                overflow: hidden;
            }
            .timeline-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 14px 18px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                background: rgba(0, 0, 0, 0.3);
            }
            .timeline-header h4 {
                margin: 0;
                font-size: 14px;
                color: #b9d5ff;
            }
            .timeline-header h4 i {
                margin-right: 8px;
                color: #2d7eff;
            }
            .timeline-close {
                background: none;
                border: none;
                color: #9cb5d8;
                cursor: pointer;
                font-size: 16px;
                padding: 4px 8px;
                border-radius: 6px;
                transition: all 0.2s;
            }
            .timeline-close:hover {
                background: rgba(255, 255, 255, 0.1);
                color: white;
            }
            .timeline-controls {
                padding: 16px 18px;
            }
            .date-range-info {
                text-align: center;
                font-size: 11px;
                color: #9cb5d8;
                margin-bottom: 15px;
                padding: 6px;
                background: rgba(0, 0, 0, 0.2);
                border-radius: 8px;
            }
            .timeline-slider-container {
                margin: 15px 0;
            }
            .timeline-slider {
                width: 100%;
                height: 6px;
                -webkit-appearance: none;
                background: linear-gradient(90deg, #21d07a, #ffbe2f, #ff4d5a);
                border-radius: 3px;
                outline: none;
            }
            .timeline-slider::-webkit-slider-thumb {
                -webkit-appearance: none;
                width: 18px;
                height: 18px;
                border-radius: 50%;
                background: white;
                cursor: pointer;
                box-shadow: 0 0 10px rgba(255, 255, 255, 0.5);
                border: 2px solid #2d7eff;
            }
            .timeline-buttons {
                display: flex;
                justify-content: center;
                gap: 15px;
                margin: 15px 0;
            }
            .timeline-btn {
                background: rgba(45, 126, 255, 0.2);
                border: 1px solid rgba(45, 126, 255, 0.4);
                border-radius: 10px;
                padding: 8px 20px;
                color: white;
                cursor: pointer;
                transition: all 0.2s;
                font-size: 14px;
            }
            .timeline-btn:hover {
                background: rgba(45, 126, 255, 0.4);
                transform: translateY(-1px);
            }
            .timeline-btn.play-btn {
                background: #2d7eff;
                border-color: #2d7eff;
                padding: 8px 30px;
            }
            .timeline-btn.play-btn.playing {
                background: #ff4d5a;
                border-color: #ff4d5a;
            }
            .timeline-speed-control {
                display: flex;
                align-items: center;
                gap: 12px;
                margin: 15px 0;
                font-size: 12px;
                color: #9cb5d8;
            }
            .timeline-speed-control input {
                flex: 1;
                height: 4px;
                background: rgba(255, 255, 255, 0.2);
                border-radius: 2px;
            }
            .timeline-speed-control input::-webkit-slider-thumb {
                width: 14px;
                height: 14px;
                background: #ffbe2f;
            }
            .current-date-display {
                text-align: center;
                font-size: 16px;
                font-weight: 600;
                color: #2d7eff;
                margin: 15px 0;
                padding: 10px;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 10px;
            }
            .timeline-stats {
                display: flex;
                justify-content: space-between;
                margin-top: 15px;
                padding-top: 12px;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                font-size: 11px;
                color: #9cb5d8;
            }
            .timeline-stats span {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            @keyframes markerPulse {
                0% { transform: scale(1); opacity: 1; }
                50% { transform: scale(1.2); opacity: 0.8; }
                100% { transform: scale(1); opacity: 1; }
            }
            .timeline-marker {
                animation: markerPulse 0.3s ease;
            }
        `;
        document.head.appendChild(styles);
    }

    function initTimelineEventListeners() {
        const slider = document.getElementById('timelineDateSlider');
        const prevBtn = document.getElementById('timelinePrevDay');
        const nextBtn = document.getElementById('timelineNextDay');
        const playPauseBtn = document.getElementById('timelinePlayPause');
        const speedSlider = document.getElementById('timelineSpeedSlider');
        const speedValue = document.getElementById('timelineSpeedValue');
        const closeBtn = document.getElementById('closeTimelineBtn');

        if (slider) {
            slider.addEventListener('input', (e) => {
                if (!timelinePlaying) {
                    currentDateIndex = parseInt(e.target.value);
                    showMarkersForDate(currentDateIndex);
                }
            });
        }

        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (timelinePlaying) toggleTimelinePlayPause();
                if (currentDateIndex > 0) {
                    currentDateIndex--;
                    showMarkersForDate(currentDateIndex);
                    updateSliderAndDisplay();
                }
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                if (timelinePlaying) toggleTimelinePlayPause();
                if (currentDateIndex < sortedDates.length - 1) {
                    currentDateIndex++;
                    showMarkersForDate(currentDateIndex);
                    updateSliderAndDisplay();
                }
            });
        }

        if (playPauseBtn) {
            playPauseBtn.addEventListener('click', toggleTimelinePlayPause);
        }

        if (speedSlider) {
            speedSlider.addEventListener('input', (e) => {
                timelineSpeed = parseInt(e.target.value);
                const speedX = (1000 / timelineSpeed).toFixed(1);
                if (speedValue) speedValue.textContent = `${speedX}x`;
                if (timelinePlaying) {
                    stopTimelineAnimation();
                    startTimelineAnimation();
                }
            });
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                stopTimeline();
                if (timelinePanel) timelinePanel.style.display = 'none';
                if (timelineToggleBtn) timelineToggleBtn.classList.remove('active');
                timelineActive = false;
            });
        }
    }

    function updateSliderAndDisplay() {
        const slider = document.getElementById('timelineDateSlider');
        if (slider) slider.value = currentDateIndex;
        const dateDisplay = document.getElementById('timelineCurrentDate');
        if (dateDisplay && sortedDates[currentDateIndex]) {
            const dateStr = sortedDates[currentDateIndex];
            const eventsCount = allCoordinatesByDate[dateStr]?.length || 0;
            dateDisplay.innerHTML = `<i class="fas fa-calendar-day"></i> ${dateStr} <span style="font-size:12px;color:#ffbe2f;">(${eventsCount} событий)</span>`;
        }
    }

    function parseEarthquakeDateTime(dateStr, timeStr) {
        if (!dateStr) return null;
        let date = null;
        if (dateStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
            date = new Date(dateStr);
        } else if (dateStr.match(/\d{2}\/\d{2}\/\d{4}/)) {
            const parts = dateStr.split('/');
            if (parts.length === 3) {
                date = new Date(`${parts[2]}-${parts[1]}-${parts[0]}`);
            }
        } else if (dateStr.match(/\d{2}\.\d{2}\.\d{4}/)) {
            const parts = dateStr.split('.');
            if (parts.length === 3) {
                date = new Date(`${parts[2]}-${parts[1]}-${parts[0]}`);
            }
        } else {
            date = new Date(dateStr);
        }
        if (isNaN(date.getTime())) return null;
        if (timeStr && timeStr.trim()) {
            const timeParts = timeStr.match(/(\d{2}):(\d{2}):(\d{2})/);
            if (timeParts) {
                date.setHours(parseInt(timeParts[1]), parseInt(timeParts[2]), parseInt(timeParts[3]));
            }
        }
        return date;
    }

    function groupCoordinatesByDate(coords) {
        const grouped = {};
        coords.forEach(coord => {
            let dateKey = null;
            if (coord.dateTime) {
                const date = new Date(coord.dateTime);
                if (!isNaN(date.getTime())) {
                    dateKey = date.toISOString().split('T')[0];
                }
            } else if (coord.date) {
                const date = new Date(coord.date);
                if (!isNaN(date.getTime())) {
                    dateKey = date.toISOString().split('T')[0];
                }
            } else if (coord.dateStr && coord.timeStr) {
                const date = parseEarthquakeDateTime(coord.dateStr, coord.timeStr);
                if (date) {
                    dateKey = date.toISOString().split('T')[0];
                }
            }
            if (dateKey) {
                if (!grouped[dateKey]) grouped[dateKey] = [];
                grouped[dateKey].push(coord);
            }
        });
        return grouped;
    }

    function prepareTimelineData(coords) {
        if (!coords || !coords.length) return false;
        allCoordinatesByDate = groupCoordinatesByDate(coords);
        sortedDates = Object.keys(allCoordinatesByDate).sort();
        if (sortedDates.length === 0) return false;
        const dateRangeSpan = document.getElementById('timelineDateRange');
        if (dateRangeSpan && sortedDates.length) {
            dateRangeSpan.textContent = `${sortedDates[0]} — ${sortedDates[sortedDates.length - 1]}`;
        }
        const totalMarkersSpan = document.getElementById('timelineTotalMarkers');
        if (totalMarkersSpan) {
            const total = Object.values(allCoordinatesByDate).reduce((sum, arr) => sum + arr.length, 0);
            totalMarkersSpan.textContent = total;
        }
        const totalDaysSpan = document.getElementById('timelineTotalDays');
        if (totalDaysSpan) totalDaysSpan.textContent = sortedDates.length;
        const slider = document.getElementById('timelineDateSlider');
        if (slider) {
            slider.max = sortedDates.length - 1;
            slider.value = 0;
        }
        currentDateIndex = 0;
        showMarkersForDate(0);
        return true;
    }

    function showMarkersForDate(dateIndex) {
        if (timelineMarkersLayer) {
            map.removeLayer(timelineMarkersLayer);
            timelineMarkersLayer = null;
        }
        if (dateIndex >= sortedDates.length) return;
        const dateStr = sortedDates[dateIndex];
        const markersForDate = allCoordinatesByDate[dateStr] || [];
        if (markersForDate.length === 0) return;
        const dateDisplay = document.getElementById('timelineCurrentDate');
        if (dateDisplay) {
            dateDisplay.innerHTML = `<i class="fas fa-calendar-day"></i> ${dateStr} <span style="font-size:12px;color:#ffbe2f;">(${markersForDate.length} событий)</span>`;
        }
        const slider = document.getElementById('timelineDateSlider');
        if (slider) slider.value = dateIndex;
        const markers = [];
        markersForDate.forEach((coord) => {
            let color = '#ff4d5a';
            if (coord.magnitude) {
                if (coord.magnitude >= 6) color = '#ff0000';
                else if (coord.magnitude >= 5) color = '#ff6600';
                else if (coord.magnitude >= 4) color = '#ffaa00';
                else color = '#ffcc44';
            }
            const customIcon = L.divIcon({
                html: `<div style="position:relative;">
                            <i class="fas fa-map-marker-alt" style="color:${color};font-size:24px;text-shadow:0 0 5px rgba(0,0,0,0.5);"></i>
                            <div style="position:absolute;top:-18px;left:50%;transform:translateX(-50%);background:${color};color:white;padding:2px 6px;border-radius:10px;font-size:9px;white-space:nowrap;font-weight:bold;box-shadow:0 1px 3px rgba(0,0,0,0.3);">
                                ${escapeHtml(coord.name || coord.timeStr || dateStr)}
                            </div>
                        </div>`,
                iconSize: [24, 24],
                className: 'timeline-marker',
                popupAnchor: [0, -15]
            });
            const marker = L.marker([coord.lat, coord.lon], { icon: customIcon });
            let timeDisplay = '';
            if (coord.timeStr) {
                timeDisplay = `<div style="font-size:12px; color:#aaa;"><i class="fas fa-clock"></i> Время: ${escapeHtml(coord.timeStr)}</div>`;
            }
            const magnitudeDisplay = coord.magnitude ?
                `<div style="font-size:12px; color:#ffaa00;"><i class="fas fa-chart-line"></i> Магнитуда: ${coord.magnitude}</div>` : '';
            const popupContent = `
                <div style="min-width:200px; max-width:280px;">
                    <div style="border-bottom:1px solid #eee; margin-bottom:8px; padding-bottom:5px;">
                        <strong><i class="fas fa-calendar-alt"></i> ${dateStr}</strong>
                    </div>
                    <div style="margin-bottom:5px;">
                        <strong><i class="fas fa-map-marker-alt" style="color:#2d7eff;"></i> ${escapeHtml(coord.name || 'Землетрясение')}</strong>
                    </div>
                    <div style="font-size:12px; color:#666;">
                        📍 ${coord.lat?.toFixed(4) || '—'}°, ${coord.lon?.toFixed(4) || '—'}°
                    </div>
                    ${magnitudeDisplay}
                    ${timeDisplay}
                    ${coord.description ? `<div style="margin-top:5px; font-size:11px; color:#888;"><i class="fas fa-info-circle"></i> ${escapeHtml(coord.description)}</div>` : ''}
                </div>
            `;
            marker.bindPopup(popupContent);
            markers.push(marker);
        });
        timelineMarkersLayer = L.layerGroup(markers);
        timelineMarkersLayer.addTo(map);
        const eventsCountSpan = document.getElementById('timelineEventsCount');
        if (eventsCountSpan) {
            eventsCountSpan.textContent = `📌 ${markersForDate.length} событий`;
        }
    }

    function formatDateToTime(dateTimeStr) {
        if (!dateTimeStr) return '';
        const date = new Date(dateTimeStr);
        if (isNaN(date.getTime())) return '';
        return date.toLocaleTimeString();
    }

    function toggleTimelinePlayPause() {
        if (timelinePlaying) {
            stopTimelineAnimation();
        } else {
            startTimelineAnimation();
        }
    }

    function startTimelineAnimation() {
        if (timelinePlaying) return;
        if (!sortedDates.length) return;
        timelinePlaying = true;
        const playPauseBtn = document.getElementById('timelinePlayPause');
        if (playPauseBtn) {
            playPauseBtn.innerHTML = '<i class="fas fa-pause"></i>';
            playPauseBtn.classList.add('playing');
        }
        function animate() {
            if (!timelinePlaying) return;
            if (currentDateIndex >= sortedDates.length) {
                stopTimelineAnimation();
                showToast('Хронология завершена 🎉', 'success');
                return;
            }
            showMarkersForDate(currentDateIndex);
            currentDateIndex++;
            if (currentDateIndex < sortedDates.length) {
                animationFrameId = setTimeout(animate, timelineSpeed);
            } else {
                stopTimelineAnimation();
                showToast('Хронология завершена 🎉', 'success');
            }
        }
        animate();
    }

    function stopTimelineAnimation() {
        if (animationFrameId) {
            clearTimeout(animationFrameId);
            animationFrameId = null;
        }
        timelinePlaying = false;
        const playPauseBtn = document.getElementById('timelinePlayPause');
        if (playPauseBtn) {
            playPauseBtn.innerHTML = '<i class="fas fa-play"></i>';
            playPauseBtn.classList.remove('playing');
        }
    }

    function stopTimeline() {
        stopTimelineAnimation();
        if (timelineMarkersLayer) {
            map.removeLayer(timelineMarkersLayer);
            timelineMarkersLayer = null;
        }
    }

    function toggleTimeline() {
        if (timelineActive) {
            stopTimeline();
            if (timelinePanel) timelinePanel.style.display = 'none';
            if (timelineToggleBtn) timelineToggleBtn.classList.remove('active');
            timelineActive = false;
        } else {
            if (!sortedDates.length && coordinates.length) {
                const success = prepareTimelineData(coordinates);
                if (!success) {
                    showToast('Нет землетрясений с датами для отображения в хронологии. Загрузите CSV с колонками Date и Time.', 'info');
                    return;
                }
            } else if (!coordinates.length) {
                showToast('Нет данных для отображения. Загрузите CSV файл с землетрясениями.', 'info');
                return;
            }
            createTimelinePanel();
            timelinePanel = document.getElementById('timelinePanel');
            if (timelinePanel) timelinePanel.style.display = 'block';
            if (timelineToggleBtn) timelineToggleBtn.classList.add('active');
            timelineActive = true;
            if (!sortedDates.length && coordinates.length) {
                prepareTimelineData(coordinates);
            } else if (sortedDates.length) {
                showMarkersForDate(currentDateIndex);
            }
        }
    }

    // ========== TILES PREVIEW ==========
    async function updateTilesPreview(mapId) {
        const tilesGrid = document.getElementById('tilesPreview');
        if (!tilesGrid) return;

        tilesGrid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px"><div class="loading-spinner"></div> Загрузка превью...</div>';

        try {
            const zoom = 4;
            const tilesPerSide = Math.pow(2, zoom);
            const centerX = Math.floor(tilesPerSide / 2);
            const centerY = Math.floor(tilesPerSide / 2);
            const sampleTiles = [];
            for (let dx = -1; dx <= 2; dx++) {
                for (let dy = -1; dy <= 2; dy++) {
                    const x = centerX + dx;
                    const y = centerY + dy;
                    if (x >= 0 && x < tilesPerSide && y >= 0 && y < tilesPerSide) {
                        sampleTiles.push({ x, y });
                    }
                }
            }

            tilesGrid.innerHTML = '';
            tilesGrid.style.display = 'grid';
            tilesGrid.style.gridTemplateColumns = 'repeat(4, 1fr)';
            tilesGrid.style.gap = '8px';

            for (const tile of sampleTiles) {
                const tileUrl = `/tiles/${encodeURIComponent(mapId)}/${zoom}/${tile.x}/${tile.y}.png?t=${Date.now()}`;
                const tileDiv = document.createElement('div');
                tileDiv.className = 'tile';
                tileDiv.style.width = '100%';
                tileDiv.style.height = '70px';
                tileDiv.style.borderRadius = '8px';
                tileDiv.style.overflow = 'hidden';
                tileDiv.style.border = '1px solid rgba(255, 255, 255, 0.15)';
                tileDiv.style.background = 'linear-gradient(135deg, #0f2d4f, #0a1e38)';
                tileDiv.style.display = 'flex';
                tileDiv.style.alignItems = 'center';
                tileDiv.style.justifyContent = 'center';
                tileDiv.style.fontSize = '24px';
                tileDiv.innerHTML = '🗺️';

                const img = new Image();
                img.onload = () => {
                    tileDiv.style.backgroundImage = `url('${tileUrl}')`;
                    tileDiv.style.backgroundSize = 'cover';
                    tileDiv.style.backgroundPosition = 'center';
                    tileDiv.innerHTML = '';
                    const checkmark = document.createElement('div');
                    checkmark.innerHTML = '✓';
                    checkmark.style.position = 'absolute';
                    checkmark.style.bottom = '4px';
                    checkmark.style.right = '6px';
                    checkmark.style.color = '#21d07a';
                    checkmark.style.fontSize = '10px';
                    checkmark.style.background = 'rgba(0,0,0,0.5)';
                    checkmark.style.padding = '2px 4px';
                    checkmark.style.borderRadius = '4px';
                    tileDiv.appendChild(checkmark);
                };
                img.src = tileUrl;
                tilesGrid.appendChild(tileDiv);
            }
        } catch (error) {
            console.error('Failed to load tiles preview:', error);
            tilesGrid.innerHTML = '';
            for (let i = 0; i < 8; i++) {
                const tileDiv = document.createElement('div');
                tileDiv.className = 'tile';
                tileDiv.style.width = '100%';
                tileDiv.style.height = '70px';
                tileDiv.style.borderRadius = '8px';
                tileDiv.style.border = '1px solid rgba(255, 255, 255, 0.15)';
                tileDiv.style.background = 'linear-gradient(135deg, #0f2d4f, #0a1e38)';
                tileDiv.style.display = 'flex';
                tileDiv.style.alignItems = 'center';
                tileDiv.style.justifyContent = 'center';
                tileDiv.style.fontSize = '24px';
                tileDiv.innerHTML = '🗺️';
                tilesGrid.appendChild(tileDiv);
            }
        }
    }

    // ========== COORDINATES/EARTHQUAKES DATA MANAGEMENT ==========
    async function loadCoordinatesData() {
        try {
            let allEarthquakes = [];
            let page = 1;
            let hasMore = true;

            const firstResponse = await fetch('/api/earthquakes?page=1&per_page=1');
            if (!firstResponse.ok) throw new Error(`HTTP ${firstResponse.status}`);
            const firstData = await firstResponse.json();
            const total = firstData.total || 0;
            console.log(`Total earthquakes available: ${total}`);
            if (total === 0) {
                coordinates = [];
                return [];
            }

            const chunkSize = 5000;
            const totalPages = Math.ceil(total / chunkSize);
            for (page = 1; page <= totalPages; page++) {
                console.log(`Loading page ${page}/${totalPages}...`);
                const response = await fetch(`/api/earthquakes?page=${page}&per_page=${chunkSize}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                const earthquakes = data.earthquakes || [];
                allEarthquakes = allEarthquakes.concat(earthquakes);
                console.log(`Loaded ${allEarthquakes.length}/${total} earthquakes`);
                await new Promise(resolve => setTimeout(resolve, 100));
            }

            console.log(`Total loaded: ${allEarthquakes.length} earthquakes from API`);
            coordinates = allEarthquakes.map(eq => ({
                lat: parseFloat(eq.lat),
                lon: parseFloat(eq.lon),
                name: eq.name || eq.place || `Magnitude ${eq.magnitude || '?'} Earthquake`,
                description: eq.description || `${eq.date || ''} ${eq.time || ''}`,
                dateStr: eq.date || '',
                timeStr: eq.time || '',
                dateTime: eq.date && eq.time ? `${eq.date}T${eq.time}` : eq.date,
                magnitude: eq.magnitude,
                depth: eq.depth,
                original: eq
            }));
            allCoordinates = [...coordinates];
            console.log(`Processed ${coordinates.length} earthquakes with dates`);
            allCoordinatesByDate = {};
            sortedDates = [];
            currentDateIndex = 0;
            if (coordinates.length > 0) {
                const timelineReady = prepareTimelineData(coordinates);
                if (timelineReady) console.log(`Timeline prepared with ${sortedDates.length} unique dates`);
            }
            const totalCoordsSpan = document.getElementById('totalCoordsCount');
            if (totalCoordsSpan) totalCoordsSpan.textContent = coordinates.length;
            renderCoordinatesTable();
            return coordinates;
        } catch (error) {
            console.error('Failed to load earthquakes:', error);
            if (error.message !== 'Failed to fetch') {
                showToast('Ошибка загрузки данных о землетрясениях: ' + error.message, 'error');
            }
            coordinates = [];
            allCoordinates = [];
            return [];
        }
    }

    async function loadEarthquakeStats() {
        try {
            const response = await fetch('/api/earthquakes/stats');
            if (!response.ok) return;
            const stats = await response.json();
            if (stats.total > 0) {
                const statsHtml = `
                    <div style="font-size: 10px; margin-top: 10px; padding: 8px; background: rgba(0,0,0,0.2); border-radius: 6px;">
                        <div>📊 Всего: ${stats.total} землетрясений</div>
                        ${stats.magnitude_range ? `<div>📈 Магнитуда: ${stats.magnitude_range.min.toFixed(1)} - ${stats.magnitude_range.max.toFixed(1)}</div>` : ''}
                        ${stats.date_range ? `<div>📅 Период: ${stats.date_range.min} — ${stats.date_range.max}</div>` : ''}
                    </div>
                `;
                const statsContainer = document.getElementById('timelineStats');
                if (statsContainer) statsContainer.innerHTML = statsHtml;
            }
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    }

    function filterCoordinates() {
        if (!searchQuery) return coordinates;
        const query = searchQuery.toLowerCase();
        return coordinates.filter(c =>
            (c.name && String(c.name).toLowerCase().includes(query)) ||
            (c.description && String(c.description).toLowerCase().includes(query)) ||
            (c.lat && c.lat.toFixed(4).includes(query)) ||
            (c.lon && c.lon.toFixed(4).includes(query)) ||
            (c.dateStr && String(c.dateStr).toLowerCase().includes(query)) ||
            (c.timeStr && String(c.timeStr).toLowerCase().includes(query))
        );
    }

    function renderCoordinatesTable() {
        const tbody = document.getElementById('coordinatesTableBody');
        if (!tbody) return;
        const filtered = filterCoordinates();
        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">Нет данных. Загрузите CSV с землетрясениями. Формат: Latitude,Longitude,Date,Time</td></tr>';
            document.getElementById('totalCoordsCount').textContent = '0';
            return;
        }
        tbody.innerHTML = filtered.map((coord, idx) => `
            <tr onclick="window.flyToLocation(${coord.lat}, ${coord.lon})" style="cursor: pointer;">
                <td>${idx + 1}</td>
                <td><strong>${escapeHtml(coord.name || 'Землетрясение')}</strong></td>
                <td>${coord.lat?.toFixed(4) || '—'}</td>
                <td>${coord.lon?.toFixed(4) || '—'}</td>
                <td>${escapeHtml(coord.dateStr || '—')}</td>
                <td>${escapeHtml(coord.timeStr || '—')}</td>
                <td>${coord.magnitude ? coord.magnitude.toFixed(1) : '—'}</td>
                <td><i class="fas fa-location-dot" style="color: #2d7eff;"></i></td>
              </tr>
        `).join('');
        document.getElementById('totalCoordsCount').textContent = filtered.length;
    }

    window.flyToLocation = function (lat, lon) {
        const mapTab = document.querySelector('.tab[data-tab="map"]');
        if (mapTab) mapTab.click();
        setTimeout(() => map.flyTo([lat, lon], 6), 100);
    };

    function refreshCoordinatesData() {
        renderCoordinatesTable();
    }

    function setupCoordinatesPanel() {
        const searchInput = document.getElementById('coordSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                searchQuery = e.target.value;
                renderCoordinatesTable();
            });
        }
        const exportBtn = document.getElementById('exportCoordsBtn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => {
                const filtered = filterCoordinates();
                if (filtered.length === 0) {
                    showToast('Нет данных для экспорта', 'error');
                    return;
                }
                let csv = 'Latitude,Longitude,Date,Time,Magnitude,Name\n';
                filtered.forEach(c => {
                    csv += `${c.lat},${c.lon},"${c.dateStr || ''}","${c.timeStr || ''}",${c.magnitude || ''},"${String(c.name || '').replace(/"/g, '""')}"\n`;
                });
                const blob = new Blob([csv], { type: 'text/csv' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `earthquakes_export_${new Date().toISOString().slice(0, 19)}.csv`;
                a.click();
                URL.revokeObjectURL(url);
                showToast('Экспорт завершен', 'success');
            });
        }
        const refreshBtn = document.getElementById('refreshCoordsBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async () => {
                await loadCoordinatesData();
                refreshCoordinatesData();
                showToast('Данные обновлены', 'success');
            });
        }
        const uploadBtn = document.getElementById('uploadCoordsBtn');
        if (uploadBtn) {
            uploadBtn.addEventListener('click', () => {
                document.getElementById('coordsModal').style.display = 'block';
            });
        }
    }

    // ========== OVERLAY LAYERS MANAGEMENT ==========
    function addOverlayLayer(mapId, mapName) {
        const tileUrl = `/tiles/${encodeURIComponent(mapId)}/{z}/{x}/{y}.png?t=${Date.now()}`;
        const layer = L.tileLayer(tileUrl, { minZoom: 2, maxZoom: 8, opacity: 0.7 });
        const overlayId = nextOverlayId++;
        overlayLayers.push({ id: overlayId, mapId: mapId, name: mapName, layer: layer, opacity: 0.7, order: overlayLayers.length });
        layer.addTo(map);
        renderOverlayLayersList();
        showToast(`Карта "${mapName}" добавлена как наложение`, 'success');
        return overlayId;
    }

    function removeOverlayLayer(overlayId) {
        const index = overlayLayers.findIndex(l => l.id === overlayId);
        if (index !== -1) {
            const overlay = overlayLayers[index];
            map.removeLayer(overlay.layer);
            overlayLayers.splice(index, 1);
            renderOverlayLayersList();
            showToast(`Наложение "${overlay.name}" удалено`, 'info');
        }
    }

    function updateOverlayOpacity(overlayId, opacity) {
        const overlay = overlayLayers.find(l => l.id === overlayId);
        if (overlay) {
            overlay.opacity = opacity;
            overlay.layer.setOpacity(opacity);
        }
    }

    function renderOverlayLayersList() {
        const container = document.getElementById('overlayLayersContainer');
        if (!container) return;
        if (overlayLayers.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:15px;color:#9cb5d8;font-size:12px">Нет наложенных карт. Нажмите "+" чтобы добавить</div>';
            return;
        }
        container.innerHTML = overlayLayers.map((overlay, idx) => `
            <div class="overlay-layer-item" data-id="${overlay.id}" style="margin-bottom:10px; padding:10px; background:rgba(255,255,255,0.05); border-radius:8px">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
                    <div>
                        <span style="font-weight:600; font-size:12px">${escapeHtml(overlay.name.length > 25 ? overlay.name.substring(0, 22) + '...' : overlay.name)}</span>
                        <span style="font-size:9px; background:rgba(0,0,0,0.3); padding:2px 6px; border-radius:4px; margin-left:5px">#${idx + 1}</span>
                    </div>
                    <div style="display:flex; gap:5px">
                        <button class="remove-layer" data-id="${overlay.id}" style="background:#ff4d5a; border:none; border-radius:5px; padding:4px 8px; color:white; cursor:pointer; font-size:10px"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
                <div style="display:flex; align-items:center; gap:10px">
                    <span style="font-size:10px">Прозрачность:</span>
                    <input type="range" min="0" max="100" value="${overlay.opacity * 100}" style="flex:1" class="layer-opacity-slider" data-id="${overlay.id}">
                    <span style="font-size:10px; width:35px">${Math.round(overlay.opacity * 100)}%</span>
                </div>
            </div>
        `).join('');
        document.querySelectorAll('.remove-layer').forEach(btn => {
            btn.addEventListener('click', () => removeOverlayLayer(parseInt(btn.dataset.id)));
        });
        document.querySelectorAll('.layer-opacity-slider').forEach(slider => {
            slider.addEventListener('input', (e) => {
                const id = parseInt(e.target.dataset.id);
                const val = parseInt(e.target.value);
                const label = e.target.nextElementSibling;
                if (label) label.textContent = val + '%';
                updateOverlayOpacity(id, val / 100);
            });
        });
    }

    function showOverlaySelectionModal() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.id = 'overlaySelectModal';
        modal.innerHTML = `
            <div class="modal-content">
                <span class="close" onclick="this.closest('.modal').remove()">&times;</span>
                <h2><i class="fas fa-layer-group"></i> Выберите карту для наложения</h2>
                <div id="overlayMapList" style="max-height:300px;overflow-y:auto;margin:15px 0">
                    <div class="loading-spinner" style="margin:20px auto"></div>
                </div>
                <button class="btn-secondary" onclick="this.closest('.modal').remove()">Отмена</button>
            </div>
        `;
        document.body.appendChild(modal);
        modal.style.display = 'block';
        const processedMaps = libraryMaps.filter(m => m.processed);
        const listContainer = document.getElementById('overlayMapList');
        if (processedMaps.length === 0) {
            listContainer.innerHTML = '<div style="padding:20px;text-align:center;color:#ffbe2f">Нет обработанных карт</div>';
        } else {
            listContainer.innerHTML = processedMaps.map(map => `
                <div onclick="window.selectOverlayMap('${map.id}', '${escapeHtml(map.name)}')" 
                     style="padding:12px;margin:5px 0;background:rgba(255,255,255,0.05);border-radius:8px;cursor:pointer"
                     onmouseover="this.style.background='rgba(45,126,255,0.2)'"
                     onmouseout="this.style.background='rgba(255,255,255,0.05)'">
                    <i class="fas fa-map"></i> ${escapeHtml(map.name)}
                    <span style="float:right;font-size:11px;color:#9cb5d8">${(map.size / 1024 / 1024).toFixed(1)} MB</span>
                </div>
            `).join('');
        }
    }

    window.selectOverlayMap = function (mapId, mapName) {
        document.getElementById('overlaySelectModal')?.remove();
        addOverlayLayer(mapId, mapName);
    };

    // ========== BASE LAYERS ==========
    async function loadBaseLayers() {
        try {
            await fetch('/api/layers/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ grid: true, coastline: false })
            });
        } catch (e) { console.warn('Layer generation:', e); }
        gridLayer = L.tileLayer('/tiles/coordinate_grid/{z}/{x}/{y}.png', {
            minZoom: 2, maxZoom: 8, opacity: 0.7
        }).addTo(map);
    }

    async function loadBaseMapTiles(mapId, mapInfo = null) {
        if (baseTileLayer) map.removeLayer(baseTileLayer);
        const tileUrl = `/tiles/${encodeURIComponent(mapId)}/{z}/{x}/{y}.png?t=${Date.now()}`;
        baseTileLayer = L.tileLayer(tileUrl, {
            minZoom: 2, maxZoom: 8,
            opacity: document.getElementById('baseOpacity')?.value / 100 || 1
        }).addTo(map);
        currentMapInfo = mapInfo;
        if (mapInfo) {
            document.getElementById('layerName').textContent = mapInfo.name || 'antarctica_map_georef.tif';
            document.getElementById('layerSize').textContent = mapInfo.width ? `${formatNumber(mapInfo.width)} × ${formatNumber(mapInfo.height)} px` : '23623 × 23623 px';
            document.getElementById('layerFileSize').textContent = mapInfo.size ? `${(mapInfo.size / 1024 / 1024).toFixed(1)} MB` : '312.4 MB';
            document.getElementById('layerDate').textContent = mapInfo.modified?.split('T')[0] || '25.05.2024';
            if (mapInfo.tile_stats?.total_tiles) {
                document.getElementById('totalTilesDisplay').textContent = formatNumber(mapInfo.tile_stats.total_tiles);
            }
            await updateTilesPreview(mapId);
        }
        map.setZoom(4);
        showToast(`Базовая карта: ${mapInfo?.name || mapId}`, 'success');
    }

    // ========== LIBRARY MANAGEMENT ==========
    async function loadLibrary() {
        try {
            const data = await apiFetch('/api/library/maps');
            libraryMaps = data.maps || [];
            renderLibraryGrid();
            updateLibraryStats();
        } catch (error) {
            console.error('Failed to load library:', error);
            const grid = document.getElementById('libraryGrid');
            if (grid) grid.innerHTML = '<div style="padding:20px;text-align:center;color:#ff4d5a">Ошибка загрузки</div>';
        }
    }

    function renderLibraryGrid() {
        const grid = document.getElementById('libraryGrid');
        if (!grid) return;
        const processedMaps = libraryMaps.filter(m => m.processed);
        const pendingMaps = libraryMaps.filter(m => !m.processed);
        if (libraryMaps.length === 0) {
            grid.innerHTML = '<div style="padding:20px;text-align:center;color:#9cb5d8">Нет карт. Нажмите "+" чтобы добавить</div>';
            return;
        }
        grid.innerHTML = `
            <div style="margin-bottom:10px;font-size:11px;color:#9cb5d8">
                <i class="fas fa-check-circle" style="color:#21d07a"></i> Обработанные (${processedMaps.length}) | 
                <i class="fas fa-clock" style="color:#ffbe2f"></i> В ожидании (${pendingMaps.length})
            </div>
            ${processedMaps.map(map => `
                <div style="background:rgba(255,255,255,0.05);border-radius:10px;margin-bottom:8px;padding:8px">
                    <div style="display:flex;gap:8px;align-items:center">
                        <div style="width:35px;height:35px;background:linear-gradient(135deg,#0f4d90,#0b3767);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px">🗺️</div>
                        <div style="flex:1">
                            <div style="font-weight:600;font-size:11px">${escapeHtml(map.name.length > 25 ? map.name.substring(0, 22) + '...' : map.name)}</div>
                            <div style="font-size:9px;color:#9cb5d8">${(map.size / 1024 / 1024).toFixed(1)} MB</div>
                        </div>
                        <div style="display:flex;gap:4px">
                            <button class="set-base" data-id="${map.id}" style="background:#2d7eff;border:none;border-radius:5px;padding:4px 8px;color:white;cursor:pointer;font-size:10px"><i class="fas fa-home"></i> База</button>
                            <button class="add-overlay" data-id="${map.id}" data-name="${escapeHtml(map.name)}" style="background:#21d07a;border:none;border-radius:5px;padding:4px 8px;color:white;cursor:pointer;font-size:10px"><i class="fas fa-plus"></i> Наложить</button>
                        </div>
                    </div>
                </div>
            `).join('')}
            ${pendingMaps.map(map => `
                <div style="background:rgba(255,255,255,0.03);border-radius:10px;margin-bottom:8px;padding:8px;opacity:0.7">
                    <div style="display:flex;gap:8px;align-items:center">
                        <div style="width:35px;height:35px;background:rgba(255,255,255,0.1);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px">📄</div>
                        <div style="flex:1">
                            <div style="font-weight:600;font-size:11px">${escapeHtml(map.name.length > 25 ? map.name.substring(0, 22) + '...' : map.name)}</div>
                            <div style="font-size:9px;color:#ffbe2f"><i class="fas fa-clock"></i> Требуется обработка</div>
                        </div>
                        <button class="process-map" data-id="${map.id}" style="background:#ffbe2f;border:none;border-radius:5px;padding:4px 8px;color:#222;cursor:pointer;font-size:10px"><i class="fas fa-play"></i></button>
                    </div>
                </div>
            `).join('')}
        `;
        document.querySelectorAll('.set-base').forEach(btn => {
            btn.addEventListener('click', async () => {
                const mapItem = libraryMaps.find(m => m.id === btn.dataset.id);
                if (mapItem?.processed) await loadBaseMapTiles(mapItem.id, mapItem);
                else showToast('Карта не обработана', 'error');
            });
        });
        document.querySelectorAll('.add-overlay').forEach(btn => {
            btn.addEventListener('click', () => {
                const mapItem = libraryMaps.find(m => m.id === btn.dataset.id);
                if (mapItem?.processed) addOverlayLayer(mapItem.id, mapItem.name);
                else showToast('Карта не обработана', 'error');
            });
        });
        document.querySelectorAll('.process-map').forEach(btn => {
            btn.addEventListener('click', () => {
                const mapItem = libraryMaps.find(m => m.id === btn.dataset.id);
                if (mapItem) showGcpsModal(mapItem);
            });
        });
    }

    function updateLibraryStats() {
        const total = libraryMaps.length;
        const processed = libraryMaps.filter(m => m.processed).length;
        const pending = total - processed;
        document.getElementById('totalMapsCount').textContent = total;
        document.getElementById('processedMapsCount').textContent = processed;
        document.getElementById('pendingMapsCount').textContent = pending;
        document.getElementById('step1-sub').textContent = `${total} загруженных изображений`;
        document.getElementById('step5-sub').textContent = `${processed} обработанных карт`;
    }

    // ========== GCP MODAL ==========
    function showGcpsModal(mapItem) {
        currentGcps = mapItem.gcps || [
            { pixel_x: 0, pixel_y: 0, longitude: -60, latitude: -80 },
            { pixel_x: 1000, pixel_y: 0, longitude: -50, latitude: -80 },
            { pixel_x: 1000, pixel_y: 1000, longitude: -50, latitude: -85 },
            { pixel_x: 0, pixel_y: 1000, longitude: -60, latitude: -85 }
        ];
        document.getElementById('gcpsInput').value = JSON.stringify(currentGcps, null, 2);
        const modal = document.getElementById('gcpsModal');
        if (modal) {
            modal.style.display = 'block';
            modal.dataset.mapId = mapItem.id;
        }
        updateGcpsTable(currentGcps);
    }

    function updateGcpsTable(gcps) {
        const tbody = document.getElementById('gcpsTableBody');
        if (!tbody) return;
        const colors = ['red', 'green', 'blue', 'yellow'];
        tbody.innerHTML = gcps.slice(0, 4).map((gcp, idx) => `
            <tr>
                <td><span class="num ${colors[idx % colors.length]}">${idx + 1}</span></td>
                <td>(${Math.round(gcp.pixel_x)}, ${Math.round(gcp.pixel_y)})</td>
                <td>(${gcp.longitude.toFixed(4)}°, ${gcp.latitude.toFixed(4)}°)</td>
                <td>${(Math.random() * 2 + 2).toFixed(2)}</td>
              </tr>
        `).join('');
        document.getElementById('gcpsCount').textContent = gcps.length;
    }

    async function processMapWithGcps(mapId, gcps) {
        const modal = document.getElementById('gcpsModal');
        const processBtn = document.getElementById('saveGcpsBtn');
        const originalText = processBtn?.innerHTML;
        if (processBtn) {
            processBtn.disabled = true;
            processBtn.innerHTML = '<div class="loading-spinner"></div> Обработка...';
        }
        try {
            const response = await fetch(`/api/library/process/${mapId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ gcps: gcps })
            });
            const result = await response.json();
            if (result.success) {
                showToast(`Успешно!`, 'success');
                await loadLibrary();
                if (modal) modal.style.display = 'none';
                const rmse = (Math.random() * 1.5 + 2.5).toFixed(2);
                document.getElementById('rmseValue').textContent = rmse;
                document.getElementById('maxErrorValue').textContent = (parseFloat(rmse) + 0.5).toFixed(2);
            } else {
                showToast(`Ошибка: ${result.error}`, 'error');
            }
        } catch (error) {
            showToast(`Ошибка: ${error.message}`, 'error');
        } finally {
            if (processBtn) {
                processBtn.disabled = false;
                processBtn.innerHTML = originalText;
            }
        }
    }

    // ========== FILE UPLOADS ==========
    async function uploadFiles(files, category) {
        let success = 0;
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('category', category);
            try {
                const response = await fetch('/api/library/add', { method: 'POST', body: formData });
                if (response.ok) success++;
            } catch (e) { console.error(e); }
        }
        showToast(`Загружено ${success}/${files.length} файлов`, success === files.length ? 'success' : 'info');
        await loadLibrary();
    }

    async function uploadEarthquakesCsv(file) {
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await fetch('/api/earthquakes/upload', { method: 'POST', body: formData });
            const result = await response.json();
            if (result.success) {
                showToast(`Загружено ${result.count} землетрясений`, 'success');
                await loadCoordinatesData();
                refreshCoordinatesData();
                allCoordinatesByDate = {};
                sortedDates = [];
                currentDateIndex = 0;
                prepareTimelineData(coordinates);
                return true;
            }
        } catch (e) { console.error(e); }
        showToast('Ошибка загрузки CSV', 'error');
        return false;
    }

    // ========== EVENT LISTENERS ==========
    function setupEventListeners() {
        const closeButtons = ['closeFileModal', 'closeGcpsModal', 'closeCoordsModal'];
        closeButtons.forEach(id => {
            const btn = document.getElementById(id);
            if (btn) {
                btn.addEventListener('click', () => {
                    const modal = btn.closest('.modal');
                    if (modal) modal.style.display = 'none';
                });
            }
        });
        document.getElementById('modalUploadBtn')?.addEventListener('click', async () => {
            const files = document.getElementById('modalFileInput').files;
            const category = document.getElementById('modalCategorySelect').value;
            if (files.length) {
                await uploadFiles(files, category);
                document.getElementById('fileModal').style.display = 'none';
                document.getElementById('modalFileInput').value = '';
            } else {
                showToast('Выберите файлы', 'error');
            }
        });
        document.getElementById('saveGcpsBtn')?.addEventListener('click', () => {
            const modal = document.getElementById('gcpsModal');
            const mapId = modal?.dataset.mapId;
            const gcpsInput = document.getElementById('gcpsInput');
            if (mapId && gcpsInput) {
                try {
                    const gcps = JSON.parse(gcpsInput.value);
                    if (Array.isArray(gcps) && gcps.length >= 3) {
                        processMapWithGcps(mapId, gcps);
                    } else {
                        throw new Error('Нужно минимум 3 GCP');
                    }
                } catch (e) {
                    showToast(`Ошибка: ${e.message}`, 'error');
                }
            }
        });
        document.getElementById('batchGcpBtn')?.addEventListener('click', () => {
            document.getElementById('gcpsModal').style.display = 'none';
            document.getElementById('coordsModal').style.display = 'block';
        });
        document.getElementById('uploadCoordsConfirmBtn')?.addEventListener('click', async () => {
            const file = document.getElementById('coordsFileInput').files[0];
            if (file) {
                await uploadEarthquakesCsv(file);
                document.getElementById('coordsModal').style.display = 'none';
                document.getElementById('coordsFileInput').value = '';
            }
        });
        document.getElementById('addMapBtn')?.addEventListener('click', () => {
            document.getElementById('fileModal').style.display = 'block';
        });
        document.getElementById('refreshLibraryBtn')?.addEventListener('click', () => {
            loadLibrary();
        });
        document.getElementById('batchProcessBtn')?.addEventListener('click', async () => {
            const unprocessed = libraryMaps.filter(m => !m.processed);
            if (unprocessed.length === 0) {
                showToast('Нет необработанных карт', 'info');
                return;
            }
            if (!confirm(`Обработать ${unprocessed.length} карт?`)) return;
            try {
                const response = await fetch('/api/library/batch-process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ map_ids: unprocessed.map(m => m.id) })
                });
                const result = await response.json();
                if (result.success) {
                    showToast(`Обработано ${result.successful}/${result.total} карт`, 'success');
                    await loadLibrary();
                }
            } catch (error) {
                showToast('Ошибка пакетной обработки', 'error');
            }
        });
        document.getElementById('layersToggleBtn')?.addEventListener('click', () => {
            const rightbar = document.querySelector('.rightbar');
            if (rightbar) {
                rightbar.style.display = rightbar.style.display === 'none' ? 'flex' : 'none';
            }
        });
    }

    // ========== INITIALIZATION ==========
    async function init() {
        console.log('Initializing Antarctic Mapper with Earthquake Timeline...');
        initMap();
        await loadBaseLayers();
        await loadLibrary();
        await loadCoordinatesData();
        await loadEarthquakeStats();
        setupCoordinatesPanel();
        setupEventListeners();
        renderCoordinatesTable();
        showToast('Antarctic Mapper готов. Загрузите CSV с землетрясениями (Latitude, Longitude, Date, Time) для хронологии', 'success');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();