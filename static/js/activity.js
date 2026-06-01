export function showActivityHome() {
  fetch('/api/stats/')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var container = document.getElementById('home-cols');
      if (!container) return;

      var controls = document.createElement('div');
      controls.className = 'activity-controls';
      var select = document.createElement('select');
      var allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = 'All repos';
      select.appendChild(allOpt);
      data.projects.forEach(function(p) {
        var opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p.replace(/^\/home\/[^/]+\//, '~/');
        select.appendChild(opt);
      });
      select.onchange = function() {
        var url = '/api/stats/';
        if (select.value) url += '?repo=' + encodeURIComponent(select.value);
        fetch(url)
          .then(function(r) { return r.json(); })
          .then(function(newData) {
            renderHeatmap(container, newData.days);
          });
      };
      controls.appendChild(select);
      container.appendChild(controls);

      renderHeatmap(container, data.days);
    });
}

export function renderHeatmap(container, days) {
  var existing = container.querySelector('.heatmap-wrapper');
  if (existing) existing.remove();

  var countMap = {};
  days.forEach(function(d) {
    countMap[d.date] = d.count;
  });

  var counts = days.map(function(d) { return d.count; }).filter(function(c) { return c > 0; }).sort(function(a, b) { return a - b; });
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
    var ds = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    weeks[weeks.length - 1][dayIdx] = { dateStr: ds, count: countMap[ds] || 0 };
    d.setDate(d.getDate() + 1);
  }

  var numWeeks = weeks.length;
  var monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  var monthsHtml = '<div class="heatmap-months" style="grid-template-columns: 30px repeat(' + numWeeks + ', 14px);">';
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

  var dayLabels = ['Mon','','Wed','','Fri','','Sun'];
  var gridHtml = '<div class="heatmap" style="grid-template-columns: 30px repeat(' + numWeeks + ', 14px); grid-template-rows: repeat(7, 14px);">';

  for (var row = 0; row < 7; row++) {
    gridHtml += '<div class="heatmap-day-label">' + dayLabels[row] + '</div>';
    for (var col = 0; col < numWeeks; col++) {
      var cell = weeks[col] && weeks[col][row];
      if (cell) {
        var level = getLevel(cell.count);
        gridHtml += '<div class="heatmap-cell" data-date="' + cell.dateStr + '" data-count="' + cell.count + '"' + (level ? ' data-level="' + level + '"' : '') + '></div>';
      } else {
        gridHtml += '<div class="heatmap-cell" style="visibility:hidden"></div>';
      }
    }
  }
  gridHtml += '</div>';

  var legendHtml = '<div class="heatmap-legend">Less <div class="heatmap-cell"></div><div class="heatmap-cell" data-level="1"></div><div class="heatmap-cell" data-level="2"></div><div class="heatmap-cell" data-level="3"></div><div class="heatmap-cell" data-level="4"></div> More</div>';

  var wrapper = document.createElement('div');
  wrapper.className = 'heatmap-wrapper';
  wrapper.innerHTML = monthsHtml + gridHtml + legendHtml;
  container.appendChild(wrapper);

  var tooltip = null;
  wrapper.addEventListener('mouseover', function(e) {
    var cell = e.target.closest('.heatmap-cell[data-date]');
    if (!cell) return;
    if (!tooltip) {
      tooltip = document.createElement('div');
      tooltip.className = 'heatmap-tooltip';
      document.body.appendChild(tooltip);
    }
    var count = cell.dataset.count;
    var date = cell.dataset.date;
    tooltip.textContent = count + ' message' + (count === '1' ? '' : 's') + ' on ' + date;
    tooltip.style.display = 'block';
    var rect = cell.getBoundingClientRect();
    tooltip.style.left = rect.left + rect.width / 2 - tooltip.offsetWidth / 2 + 'px';
    tooltip.style.top = rect.top - tooltip.offsetHeight - 6 + 'px';
  });
  wrapper.addEventListener('mouseout', function(e) {
    if (tooltip && !e.target.closest('.heatmap-cell[data-date]')) {
      tooltip.style.display = 'none';
    }
  });
  wrapper.addEventListener('mouseleave', function() {
    if (tooltip) tooltip.style.display = 'none';
  });
}
