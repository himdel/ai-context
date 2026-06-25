export function showActivityHome() {
  fetch('/api/stats/')
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      var container = document.getElementById('home-cols');
      if (!container) return;

      var controls = document.createElement('div');
      controls.className = 'activity-controls';
      var select = document.createElement('select');
      var allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = 'All repos';
      select.appendChild(allOpt);
      data.projects.forEach(function (p) {
        var opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p.replace(/^\/home\/[^/]+\//, '~/');
        select.appendChild(opt);
      });
      select.onchange = function () {
        var url = '/api/stats/';
        if (select.value) url += '?repo=' + encodeURIComponent(select.value);
        fetch(url)
          .then(function (r) {
            return r.json();
          })
          .then(function (newData) {
            renderHeatmap(container, newData.days);
            renderLineChart(container, newData.days);
          });
      };
      controls.appendChild(select);
      container.appendChild(controls);

      renderHeatmap(container, data.days);
      renderLineChart(container, data.days);
    });
}

function renderHeatmap(container, days) {
  var existing = container.querySelector('.heatmap-wrapper');
  if (existing) existing.remove();

  var countMap = {};
  days.forEach(function (d) {
    countMap[d.date] = d.count;
  });

  var counts = days
    .map(function (d) {
      return d.count;
    })
    .filter(function (c) {
      return c > 0;
    })
    .sort(function (a, b) {
      return a - b;
    });
  var q1 = counts[Math.floor(counts.length * 0.25)] || 1;
  var q2 = counts[Math.floor(counts.length * 0.5)] || q1;
  var q3 = counts[Math.floor(counts.length * 0.75)] || q2;

  function getLevel(count) {
    if (!count) return 0;
    if (count <= q1) return 1;
    if (count <= q2) return 2;
    if (count <= q3) return 3;
    return 4;
  }

  var today = new Date();
  today.setHours(0, 0, 0, 0);

  var startDate = new Date(today);
  startDate.setDate(startDate.getDate() - 52 * 7);
  var startDow = (startDate.getDay() + 6) % 7;
  startDate.setDate(startDate.getDate() - startDow);

  var weeks = [];
  var d = new Date(startDate);
  while (d <= today) {
    var dayIdx = (d.getDay() + 6) % 7;
    if (dayIdx === 0 || weeks.length === 0) {
      weeks.push([]);
    }
    var ds =
      d.getFullYear() +
      '-' +
      String(d.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(d.getDate()).padStart(2, '0');
    weeks[weeks.length - 1][dayIdx] = { dateStr: ds, count: countMap[ds] || 0 };
    d.setDate(d.getDate() + 1);
  }

  var numWeeks = weeks.length;
  var monthNames = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];

  var monthsHtml =
    '<div class="heatmap-months" style="grid-template-columns: 30px repeat(' +
    numWeeks +
    ', 14px);">';
  monthsHtml += '<span></span>';
  var lastMonth = -1;
  for (var w = 0; w < numWeeks; w++) {
    var firstDay = weeks[w][0];
    if (firstDay) {
      var m = parseInt(firstDay.dateStr.slice(5, 7), 10) - 1;
      if (m !== lastMonth) {
        monthsHtml += '<span>' + monthNames[m] + '</span>';
        lastMonth = m;
      } else {
        monthsHtml += '<span></span>';
      }
    } else {
      monthsHtml += '<span></span>';
    }
  }
  monthsHtml += '</div>';

  var dayLabels = ['Mon', '', 'Wed', '', 'Fri', '', 'Sun'];
  var gridHtml =
    '<div class="heatmap" style="grid-template-columns: 30px repeat(' +
    numWeeks +
    ', 14px); grid-template-rows: repeat(7, 14px);">';

  for (var row = 0; row < 7; row++) {
    gridHtml += '<div class="heatmap-day-label">' + dayLabels[row] + '</div>';
    for (var col = 0; col < numWeeks; col++) {
      var cell = weeks[col] && weeks[col][row];
      if (cell) {
        var level = getLevel(cell.count);
        gridHtml +=
          '<div class="heatmap-cell" data-date="' +
          cell.dateStr +
          '" data-count="' +
          cell.count +
          '"' +
          (level ? ' data-level="' + level + '"' : '') +
          '></div>';
      } else {
        gridHtml +=
          '<div class="heatmap-cell" style="visibility:hidden"></div>';
      }
    }
  }
  gridHtml += '</div>';

  var legendHtml =
    '<div class="heatmap-legend">Less <div class="heatmap-cell"></div><div class="heatmap-cell" data-level="1"></div><div class="heatmap-cell" data-level="2"></div><div class="heatmap-cell" data-level="3"></div><div class="heatmap-cell" data-level="4"></div> More</div>';

  var wrapper = document.createElement('div');
  wrapper.className = 'heatmap-wrapper';
  wrapper.innerHTML = monthsHtml + gridHtml + legendHtml;
  container.appendChild(wrapper);

  var tooltip = null;
  wrapper.addEventListener('mouseover', function (e) {
    var cell = e.target.closest('.heatmap-cell[data-date]');
    if (!cell) return;
    if (!tooltip) {
      tooltip = document.createElement('div');
      tooltip.className = 'heatmap-tooltip';
      document.body.appendChild(tooltip);
    }
    var count = cell.dataset.count;
    var date = cell.dataset.date;
    tooltip.textContent =
      count + ' message' + (count === '1' ? '' : 's') + ' on ' + date;
    tooltip.style.display = 'block';
    var rect = cell.getBoundingClientRect();
    tooltip.style.left =
      rect.left + rect.width / 2 - tooltip.offsetWidth / 2 + 'px';
    tooltip.style.top = rect.top - tooltip.offsetHeight - 6 + 'px';
  });
  wrapper.addEventListener('mouseout', function (e) {
    if (tooltip && !e.target.closest('.heatmap-cell[data-date]')) {
      tooltip.style.display = 'none';
    }
  });
  wrapper.addEventListener('mouseleave', function () {
    if (tooltip) tooltip.style.display = 'none';
  });
}

function computeAvg(counts, windowSize) {
  var half = Math.floor(windowSize / 2);
  var result = [];
  for (var i = 0; i < counts.length; i++) {
    var lo = Math.max(0, i - half);
    var hi = Math.min(counts.length - 1, i + half);
    var sum = 0;
    for (var j = lo; j <= hi; j++) sum += counts[j];
    result.push(sum / (hi - lo + 1));
  }
  return result;
}

function renderLineChart(container, days) {
  var existing = container.querySelector('.linechart-wrapper');
  if (existing) existing.remove();

  var countMap = {};
  days.forEach(function (d) {
    countMap[d.date] = d.count;
  });

  var today = new Date();
  today.setHours(0, 0, 0, 0);
  var startDate = new Date(today);
  startDate.setDate(startDate.getDate() - 52 * 7);
  var startDow = (startDate.getDay() + 6) % 7;
  startDate.setDate(startDate.getDate() - startDow);

  var dailyData = [];
  var d = new Date(startDate);
  while (d <= today) {
    var ds =
      d.getFullYear() +
      '-' +
      String(d.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(d.getDate()).padStart(2, '0');
    dailyData.push({ date: ds, count: countMap[ds] || 0 });
    d.setDate(d.getDate() + 1);
  }

  var rawCounts = dailyData.map(function (d) {
    return d.count;
  });
  var maxCount = Math.max.apply(null, rawCounts);
  var yMax = Math.ceil(maxCount * 1.1) || 1;

  var numWeeks = Math.ceil(dailyData.length / 7);
  var paddingLeft = 30;
  var paddingTop = 5;
  var paddingBottom = 18;
  var cssWidth = paddingLeft + numWeeks * 16 - 2;
  var cssHeight = 160;
  var chartWidth = cssWidth - paddingLeft;
  var chartHeight = cssHeight - paddingTop - paddingBottom;

  var dpr = window.devicePixelRatio || 1;
  var canvas = document.createElement('canvas');
  canvas.style.width = cssWidth + 'px';
  canvas.style.height = cssHeight + 'px';
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  var ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  var gridLines = 4;
  ctx.strokeStyle = 'rgba(0,0,0,0.08)';
  ctx.lineWidth = 1;
  ctx.font = '10px system-ui, sans-serif';
  ctx.fillStyle = '#888';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (var g = 0; g <= gridLines; g++) {
    var gy = paddingTop + chartHeight - (g / gridLines) * chartHeight;
    var val = Math.round((g / gridLines) * yMax);
    ctx.beginPath();
    ctx.moveTo(paddingLeft, gy);
    ctx.lineTo(cssWidth, gy);
    ctx.stroke();
    ctx.fillText(val, paddingLeft - 4, gy);
  }

  var windows = [
    { size: 30, color: 'rgba(0,0,0,0.12)', width: 3 },
    { size: 14, color: 'rgba(0,0,0,0.22)', width: 2.5 },
    { size: 7, color: 'rgba(0,0,0,0.35)', width: 2 },
    { size: 5, color: 'rgba(0,0,0,0.45)', width: 1.5 },
    { size: 3, color: 'rgba(0,0,0,0.6)', width: 1.2 },
    { size: 2, color: 'rgba(0,0,0,0.75)', width: 1 },
    { size: 1, color: 'rgba(0,0,0,1.0)', width: 1 },
  ];

  for (var w = 0; w < windows.length; w++) {
    var avg = computeAvg(rawCounts, windows[w].size);
    ctx.beginPath();
    ctx.strokeStyle = windows[w].color;
    ctx.lineWidth = windows[w].width;
    ctx.lineJoin = 'round';
    for (var i = 0; i < avg.length; i++) {
      var x = paddingLeft + (i / (avg.length - 1)) * chartWidth;
      var y = paddingTop + chartHeight - (avg[i] / yMax) * chartHeight;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  var monthNames = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  ctx.fillStyle = '#888';
  ctx.font = '10px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  var lastMonth = -1;
  for (var i = 0; i < dailyData.length; i++) {
    var m = parseInt(dailyData[i].date.slice(5, 7), 10) - 1;
    if (m !== lastMonth) {
      lastMonth = m;
      var mx = paddingLeft + (i / (dailyData.length - 1)) * chartWidth;
      ctx.fillText(monthNames[m], mx, cssHeight - paddingBottom + 4);
    }
  }

  var wrapper = document.createElement('div');
  wrapper.className = 'linechart-wrapper';
  wrapper.appendChild(canvas);

  var hoverLine = document.createElement('div');
  hoverLine.className = 'linechart-hover-line';
  hoverLine.style.height = paddingTop + chartHeight + 'px';
  wrapper.appendChild(hoverLine);

  var hoverTooltip = document.createElement('div');
  hoverTooltip.className = 'linechart-tooltip';
  wrapper.appendChild(hoverTooltip);

  canvas.addEventListener('mousemove', function (e) {
    var rect = canvas.getBoundingClientRect();
    var mouseX = e.clientX - rect.left;
    var mouseY = e.clientY - rect.top;

    if (mouseX < paddingLeft || mouseX > paddingLeft + chartWidth) {
      hoverLine.style.display = 'none';
      hoverTooltip.style.display = 'none';
      return;
    }

    var dayIndex = Math.round(
      ((mouseX - paddingLeft) / chartWidth) * (dailyData.length - 1),
    );
    dayIndex = Math.max(0, Math.min(dailyData.length - 1, dayIndex));
    var dayX = paddingLeft + (dayIndex / (dailyData.length - 1)) * chartWidth;

    hoverLine.style.display = 'block';
    hoverLine.style.left = dayX + 'px';

    var day = dailyData[dayIndex];
    hoverTooltip.style.display = 'block';
    hoverTooltip.textContent =
      day.count + ' message' + (day.count === 1 ? '' : 's') + ' on ' + day.date;

    var tooltipLeft = dayX + 8;
    if (tooltipLeft + 160 > cssWidth) tooltipLeft = dayX - 168;
    hoverTooltip.style.left = tooltipLeft + 'px';
    hoverTooltip.style.top = Math.max(0, mouseY - 20) + 'px';
  });

  canvas.addEventListener('mouseleave', function () {
    hoverLine.style.display = 'none';
    hoverTooltip.style.display = 'none';
  });

  container.appendChild(wrapper);
}
