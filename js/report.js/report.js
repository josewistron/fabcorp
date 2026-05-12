/* ===================================
   report.js - Dashboard ABC Report
   ================================= */

let freshChart       = null;
let faeChart         = null;
let freshTrendsChart = null;
let faeTrendsChart   = null;

Chart.register(ChartDataLabels);

var FRESH_PHASES = ['A Test', 'B Test', 'C Test'];
var FAE_PHASES   = ['A Test', 'B Test', 'C Test'];

document.addEventListener('DOMContentLoaded', function() {

    var reportDateInput   = document.getElementById('reportDate');
    var loadReportBtn     = document.getElementById('loadReportBtn');
    var freshTableBody    = document.getElementById('freshTableBody');
    var faeTableBody      = document.getElementById('faeTableBody');
    var reportDateDisplay = document.getElementById('reportDateDisplay');
    var pdOutputBadge     = document.getElementById('pdOutputBadge');
    var faeOutputBadge    = document.getElementById('faeOutputBadge');
    var dbStatusEl        = document.getElementById('dbStatus');
    var footerTimeEl      = document.getElementById('footerTime');

    console.log('🔍 DOM Elements:');
    console.log('   reportDate:', reportDateInput ? '✅' : '❌');
    console.log('   loadReportBtn:', loadReportBtn ? '✅' : '❌');
    console.log('   freshTableBody:', freshTableBody ? '✅' : '❌');
    console.log('   faeTableBody:', faeTableBody ? '✅' : '❌');

    function setDefaultDate() {
        if (!reportDateInput) return;
        var today = new Date();
        var yyyy  = today.getFullYear();
        var mm    = String(today.getMonth() + 1).padStart(2, '0');
        var dd    = String(today.getDate()).padStart(2, '0');
        reportDateInput.value = yyyy + '-' + mm + '-' + dd;
    }

    function formatDateDisplay(dateStr) {
        if (!dateStr) return '--';
        var parts = dateStr.split('-');
        var months = ['Jan','Feb','Mar','Apr','May','Jun',
                      'Jul','Aug','Sep','Oct','Nov','Dec'];
        return months[parseInt(parts[1])-1] + ' ' + parts[2] + ', ' + parts[0] + ' — Cutoff 6AM to 6AM';
    }

    function startClock() {
        function update() {
            var now = new Date();
            var hh  = String(now.getHours()).padStart(2, '0');
            var mm  = String(now.getMinutes()).padStart(2, '0');
            var ss  = String(now.getSeconds()).padStart(2, '0');
            if (footerTimeEl) footerTimeEl.textContent = hh + ':' + mm + ':' + ss;
        }
        update();
        setInterval(update, 1000);
    }

    function updateDbStatus(text, isOk) {
        if (dbStatusEl) {
            dbStatusEl.textContent = text;
            dbStatusEl.style.color = isOk ? '#38bdf8' : '#f87171';
        }
    }

    function showToast(message, type) {
        var existing = document.querySelector('.toast');
        if (existing) existing.remove();
        var toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(function() {
            toast.classList.add('hide');
            setTimeout(function() { toast.remove(); }, 300);
        }, 3000);
    }

    function getYrClass(yr) {
        if (yr >= 95) return 'yr-good';
        if (yr >= 85) return 'yr-warning';
        return 'yr-bad';
    }

    function getGapClass(gap) {
        if (gap <= 5) return 'gap-good';
        if (gap <= 15) return 'gap-warning';
        return 'gap-bad';
    }

    function calculateInputGap(inputReal, inputEsperado) {
        if (!inputEsperado || inputEsperado <= 0) return null;
        var porcentaje = (inputReal / inputEsperado) * 100;
        var gap = 100 - porcentaje;
        return gap;
    }

    function ensureAllPhases(rows, phaseList) {
        var result = [];
        phaseList.forEach(function(phaseName) {
            var found = rows.find(function(r) {
                return r.phase === phaseName;
            });
            if (found) {
                result.push(found);
            } else {
                result.push({
                    phase:  phaseName,
                    input:  0,
                    passed: 0,
                    failed: 0,
                    yr:     0
                });
            }
        });
        return result;
    }

    function renderTableWithGap(tbody, rows, outputValue, outputLabel, isFae) {
        var html = '';
        var totalInput  = 0;
        var totalPassed = 0;
        var totalFailed = 0;

        rows.forEach(function(row, index) {
            var yr      = parseFloat(row.yr) || 0;
            var yrClass = getYrClass(yr);

            var inputEsperado;
            if (index === 0) {
                inputEsperado = outputValue;
            } else {
                inputEsperado = rows[index - 1].failed;
            }

            var gap = calculateInputGap(row.input, inputEsperado);
            var gapDisplay;
            var gapClass = '';

            if (gap !== null) {
                gapClass = getGapClass(Math.abs(gap));
                gapDisplay = gap.toFixed(2) + '%';
            } else {
                gapDisplay = 'N/A';
            }

            html += '<tr>';
            html += '<td>' + row.phase + '</td>';
            html += '<td>' + (row.input || 0).toLocaleString() + '</td>';
            html += '<td class="' + gapClass + '">' + gapDisplay + '</td>';
            html += '<td>' + (row.passed || 0).toLocaleString() + '</td>';
            html += '<td>' + (row.failed || 0).toLocaleString() + '</td>';
            html += '<td class="' + yrClass + '">' + yr.toFixed(2) + '%</td>';
            html += '</tr>';

            totalInput  += row.input  || 0;
            totalPassed += row.passed || 0;
            totalFailed += row.failed || 0;
        });

        var totalYr = (totalPassed + totalFailed) > 0
            ? ((totalPassed / (totalPassed + totalFailed)) * 100).toFixed(2)
            : '0.00';

        html += '<tr class="total-row">';
        html += '<td>TOTAL</td>';
        html += '<td>' + totalInput.toLocaleString() + '</td>';
        html += '<td>—</td>';
        html += '<td>' + totalPassed.toLocaleString() + '</td>';
        html += '<td>' + totalFailed.toLocaleString() + '</td>';
        html += '<td class="' + getYrClass(parseFloat(totalYr)) + '">' + totalYr + '%</td>';
        html += '</tr>';

        tbody.innerHTML = html;
    }

    function renderBarChart(canvasId, rows, label, type) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        if (type === 'fresh' && freshChart) freshChart.destroy();
        if (type === 'fae'   && faeChart)   faeChart.destroy();

        var ctx    = canvas.getContext('2d');
        var phases = rows.map(function(r) { return r.phase; });
        var passed = rows.map(function(r) { return r.passed || 0; });
        var failed = rows.map(function(r) { return r.failed || 0; });

        var chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: phases,
                datasets: [
                    {
                        label: 'Passed',
                        data: passed,
                        backgroundColor: 'rgba(16, 185, 129, 0.75)',
                        borderColor: '#059669',
                        borderWidth: 1,
                        borderRadius: 6
                    },
                    {
                        label: 'Failed',
                        data: failed,
                        backgroundColor: 'rgba(239, 68, 68, 0.75)',
                        borderColor: '#dc2626',
                        borderWidth: 1,
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { position: 'top' },
                    title: {
                        display: true,
                        text: label + ' — Passed vs Failed',
                        font: { size: 14, weight: '700' }
                    },
                    datalabels: {
                        anchor: 'end',
                        align: 'top',
                        color: '#334155',
                        font: { weight: '700', size: 12 },
                        formatter: function(value) {
                            return value > 0 ? value : '';
                        }
                    }
                },
                scales: {
                    y: { beginAtZero: true },
                    x: { grid: { display: false } }
                }
            }
        });

        if (type === 'fresh') freshChart = chart;
        if (type === 'fae')   faeChart   = chart;
    }

    function renderTrendCharts(records) {
        var freshRecords = records.filter(function(r) {
            return !r.PhaseName.toUpperCase().startsWith('FAE');
        });

        var faeRecords = records.filter(function(r) {
            return r.PhaseName.toUpperCase().startsWith('FAE');
        });

        // Generate ALL dates in the range (no gaps)
        var allDates = generateDateRange(records);

        var freshColors = {
            'A Test': '#2563eb',
            'B Test': '#8b5cf6',
            'C Test': '#f59e0b'
        };

        var faeColors = {
            'FAE A Test': '#ef4444',
            'FAE B Test': '#ec4899',
            'FAE C Test': '#f97316'
        };

        renderSingleTrendChart('freshTrendsChart', freshRecords, allDates, freshColors, false, 'fresh', FRESH_PHASES);
        renderSingleTrendChart('faeTrendsChart', faeRecords, allDates, faeColors, true, 'fae', FAE_PHASES.map(function(p) { return 'FAE ' + p; }));
    }

    // Generate every date between min and max from records
    function generateDateRange(records) {
        if (records.length === 0) return [];

        // Find min and max dates
        var minDate = null;
        var maxDate = null;

        records.forEach(function(r) {
            var dateStr = r.ReportDate.substring(0, 10);
            var d = new Date(dateStr + 'T12:00:00');
            if (minDate === null || d < minDate) minDate = new Date(d);
            if (maxDate === null || d > maxDate) maxDate = new Date(d);
        });

        // Also check the trend date inputs
        var trendsStart = document.getElementById('trendsStartDate');
        var trendsEnd   = document.getElementById('trendsEndDate');

        if (trendsStart && trendsStart.value) {
            var inputStart = new Date(trendsStart.value + 'T12:00:00');
            if (inputStart < minDate) minDate = inputStart;
        }
        if (trendsEnd && trendsEnd.value) {
            var inputEnd = new Date(trendsEnd.value + 'T12:00:00');
            if (inputEnd > maxDate) maxDate = inputEnd;
        }

        // Generate all dates
        var dates = [];
        var current = new Date(minDate);

        while (current <= maxDate) {
            var mm = String(current.getMonth() + 1).padStart(2, '0');
            var dd = String(current.getDate()).padStart(2, '0');
            dates.push(mm + '/' + dd);
            current.setDate(current.getDate() + 1);
        }

        return dates;
    }

    function renderSingleTrendChart(canvasId, records, allDates, colorMap, isFae, type, defaultPhases) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        if (type === 'fresh' && freshTrendsChart) freshTrendsChart.destroy();
        if (type === 'fae'   && faeTrendsChart)   faeTrendsChart.destroy();

        if (allDates.length === 0) {
            var ctxEmpty = canvas.getContext('2d');
            var emptyChart = new Chart(ctxEmpty, {
                type: 'line',
                data: { labels: [], datasets: [] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        datalabels: { display: false },
                        title: {
                            display: true,
                            text: 'No data available for this range',
                            font: { size: 14, weight: '600' },
                            color: '#94a3b8'
                        }
                    }
                }
            });
            if (type === 'fresh') freshTrendsChart = emptyChart;
            if (type === 'fae')   faeTrendsChart   = emptyChart;
            return;
        }

        // Use phases from records + ensure default phases exist
        var phases = [];
        if (defaultPhases) {
            defaultPhases.forEach(function(p) {
                if (phases.indexOf(p) === -1) phases.push(p);
            });
        }
        records.forEach(function(r) {
            if (phases.indexOf(r.PhaseName) === -1) phases.push(r.PhaseName);
        });

        var fallbackColors = ['#6366f1', '#14b8a6', '#f97316', '#64748b'];

        var datasets = phases.map(function(phase, idx) {
            var dataPoints = allDates.map(function(dateLabel) {
                var found = records.find(function(r) {
                    var dateStr = r.ReportDate.substring(0, 10);
                    var parts = dateStr.split('-');
                    var label = parts[1] + '/' + parts[2];
                    return label === dateLabel && r.PhaseName === phase;
                });
                return found ? parseFloat(found.YieldRate) : 0;
            });

            var displayName = isFae ? phase.replace(/^FAE\s*/i, '') : phase;
            var color = colorMap[phase] || fallbackColors[idx % fallbackColors.length];

            return {
                label: displayName + ' YR%',
                data: dataPoints,
                borderColor: color,
                backgroundColor: color,
                fill: false,
                tension: 0.35,
                pointRadius: 5,
                pointHoverRadius: 8,
                borderWidth: 2.5,
                spanGaps: false
            };
        });


        var ctx = canvas.getContext('2d');

        var chart = new Chart(ctx, {
            type: 'line',
            data: { labels: allDates, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            font: { weight: '600', size: 12 },
                            usePointStyle: true,
                            padding: 16
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.92)',
                        padding: 12,
                        cornerRadius: 10,
                        callbacks: {
                            label: function(ctx) {
                                return ctx.dataset.label + ': ' + ctx.parsed.y + '%';
                            }
                        }
                    },
                    datalabels: {
                        anchor: 'end',
                        align: 'top',
                        offset: 4,
                        color: function(context) {
                            return context.dataset.borderColor;
                        },
                        font: {
                            weight: '700',
                            size: 10
                        },
                        formatter: function(value) {
                            if (value === null || value === undefined) return '';
                            return value.toFixed(1) + '%';
                        }
                    }
                },
                scales: {
                    y: {
                        min: 0, max: 100,
                        grid: { color: 'rgba(148, 163, 184, 0.1)' },
                        ticks: {
                            callback: function(v) { return v + '%'; },
                            font: { weight: '600' }
                        }
                    },
                    x: {
                        grid: { display: false },
                        ticks: {
                            maxRotation: 45,
                            font: { size: 10, weight: '600' }
                        }
                    }
                }
            }
        });

        if (type === 'fresh') freshTrendsChart = chart;
        if (type === 'fae')   faeTrendsChart   = chart;
    }

    // ============ TRENDS DATE RANGE ============
    var trendsFilterToggle  = document.getElementById('trendsFilterToggle');
    var trendsFilterContent = document.getElementById('trendsFilterContent');
    var toggleIcon          = document.getElementById('toggleIcon');
    var trendsStartDate     = document.getElementById('trendsStartDate');
    var trendsEndDate       = document.getElementById('trendsEndDate');
    var loadTrendsBtn       = document.getElementById('loadTrendsBtn');
    var quickRangeBtns      = document.querySelectorAll('.quick-range-btn');

    function setTrendDates(days) {
        var end   = new Date();
        var start = new Date();
        start.setDate(start.getDate() - days);

        var formatDate = function(d) {
            var yyyy = d.getFullYear();
            var mm   = String(d.getMonth() + 1).padStart(2, '0');
            var dd   = String(d.getDate()).padStart(2, '0');
            return yyyy + '-' + mm + '-' + dd;
        };

        if (trendsStartDate) trendsStartDate.value = formatDate(start);
        if (trendsEndDate)   trendsEndDate.value   = formatDate(end);
    }

    if (trendsFilterToggle) {
        trendsFilterToggle.addEventListener('click', function() {
            if (trendsFilterContent) {
                trendsFilterContent.classList.toggle('open');
            }
            if (toggleIcon) {
                toggleIcon.classList.toggle('open');
            }
        });
    }

    if (quickRangeBtns.length > 0) {
        quickRangeBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                var days = parseInt(btn.getAttribute('data-days'));
                quickRangeBtns.forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                setTrendDates(days);
                loadTrendsWithRange();
            });
        });
    }

    function loadTrendsWithRange() {
        var start = trendsStartDate ? trendsStartDate.value : '';
        var end   = trendsEndDate   ? trendsEndDate.value   : '';

        if (!start || !end) {
            showToast('⚠️ Select both dates', 'error');
            return;
        }

        var url = '/api/trends?start=' + start + '&end=' + end;

        fetch(url)
            .then(function(res) { return res.json(); })
            .then(function(tdata) {
                if (tdata.success && tdata.trends && tdata.trends.length > 0) {
                    renderTrendCharts(tdata.trends);
                    showToast('📊 Trends loaded (' + tdata.trends.length + ' records)', 'success');
                } else {
                    showToast('ℹ️ No trend data for this range', 'error');
                }
            })
            .catch(function(err) {
                console.error('Trends error:', err);
                showToast('❌ Error loading trends', 'error');
            });
    }

    if (loadTrendsBtn) {
        loadTrendsBtn.addEventListener('click', loadTrendsWithRange);
    }

    setTrendDates(30);

    // ============ LOAD FULL REPORT ============
    function loadFullReport(date) {
        console.log('📡 Loading report for:', date);

        Promise.all([
            fetch('/api/report/' + date).then(function(r) { return r.json(); }),
            fetch('/api/pdoutput/' + date).then(function(r) { return r.json(); }),
            fetch('/api/faeoutput/' + date).then(function(r) { return r.json(); })
        ])
        .then(function(results) {
            var reportData = results[0];
            var pdData     = results[1];
            var faeData    = results[2];

            console.log('📦 Report:', reportData);
            console.log('📦 PDOutput:', pdData);
            console.log('📦 FAEOutput:', faeData);

            if (!reportData.success) {
                showToast('❌ ' + (reportData.error || 'Error'), 'error');
                return;
            }

            var pdOutput  = (pdData.data && pdData.data.PDOutput) || 0;
            var faeOutput = (faeData.data && faeData.data.FAEOutput) || 0;

            console.log('📊 PD Output:', pdOutput, '| FAE Output:', faeOutput);

            if (pdOutputBadge)  pdOutputBadge.textContent  = 'PD Output: ' + pdOutput;
            if (faeOutputBadge) faeOutputBadge.textContent = 'FAE Output: ' + faeOutput;

            if (reportDateDisplay) {
                reportDateDisplay.textContent = formatDateDisplay(date);
            }

            var allRows = reportData.report || [];
            console.log('📋 Total rows:', allRows.length);

            var mappedRows = allRows.map(function(row) {
                return {
                    phase:    row.PhaseName,
                    input:    row.TotalUnits   || 0,
                    passed:   row.PassedUnits  || 0,
                    failed:   row.FailedUnits  || 0,
                    yr:       row.YieldRate    || 0
                };
            });

            var freshRows = mappedRows.filter(function(r) {
                return !r.phase.toUpperCase().startsWith('FAE');
            });

            var faeRows = mappedRows.filter(function(r) {
                return r.phase.toUpperCase().startsWith('FAE');
            }).map(function(r) {
                return {
                    phase:  r.phase.replace(/^FAE\s*/i, ''),
                    input:  r.input,
                    passed: r.passed,
                    failed: r.failed,
                    yr:     r.yr
                };
            });

            freshRows = ensureAllPhases(freshRows, FRESH_PHASES);
            faeRows   = ensureAllPhases(faeRows, FAE_PHASES);

            console.log('✅ Fresh:', freshRows.length, '| FAE:', faeRows.length);

            renderTableWithGap(freshTableBody, freshRows, pdOutput, 'PD Output', false);
            renderBarChart('freshChart', freshRows, 'Fresh Units', 'fresh');

            renderTableWithGap(faeTableBody, faeRows, faeOutput, 'FAE Output', true);
            renderBarChart('faeChart', faeRows, 'FAE Units', 'fae');

            loadTrendsWithRange();

            showToast('📊 Report loaded', 'success');
        })
        .catch(function(err) {
            console.error('❌ Error:', err);
            showToast('❌ Error: ' + err.message, 'error');
        });
    }

    // ============ HANDLERS ============
    function handleLoad() {
        var date = reportDateInput.value;
        if (!date) {
            showToast('⚠️ Select a date', 'error');
            return;
        }

        loadReportBtn.disabled  = true;
        loadReportBtn.innerHTML = '<span class="refresh-icon">⏳</span> Loading...';

        loadFullReport(date);

        setTimeout(function() {
            loadReportBtn.disabled  = false;
            loadReportBtn.innerHTML = '<span class="refresh-icon">📊</span> Load Report';
        }, 2000);
    }

    function checkDb() {
        fetch('/api/health')
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.status === 'connected') {
                    updateDbStatus('Connected ✅', true);
                    console.log('✅ DB connected');
                } else {
                    updateDbStatus('Disconnected ❌', false);
                }
            })
            .catch(function(err) {
                updateDbStatus('No connection ❌', false);
                console.error('DB check failed:', err);
            });
    }

    // ============ EVENT LISTENERS ============
    if (loadReportBtn) {
        loadReportBtn.addEventListener('click', handleLoad);
    }
    if (reportDateInput) {
        reportDateInput.addEventListener('change', handleLoad);
    }

    // ============ INIT ============
    setDefaultDate();
    startClock();
    checkDb();

    console.log('🚀 report.js loaded successfully');
});
