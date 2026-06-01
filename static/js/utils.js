var _loadCache = {};
export function loadScript(url) {
  if (!_loadCache[url]) {
    _loadCache[url] = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = url;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  return _loadCache[url];
}
export function loadCSS(url) {
  if (!_loadCache[url]) {
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    document.head.appendChild(link);
    _loadCache[url] = Promise.resolve();
  }
  return _loadCache[url];
}

export function isNearBottom(el, threshold) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < (threshold || 150);
}

export function timeAgo(iso) {
  try {
    var ms = Date.now() - new Date(iso).getTime();
    if (ms < 0 || isNaN(ms)) return '';
    var secs = Math.floor(ms / 1000);
    if (secs < 60) return 'just now';
    var mins = Math.floor(secs / 60);
    if (mins < 60) return mins + 'm ago';
    var hours = Math.floor(mins / 60);
    if (hours < 24) return hours + 'h ago';
    var days = Math.floor(hours / 24);
    if (days < 30) return days + 'd ago';
    return Math.floor(days / 30) + 'mo ago';
  } catch (e) {
    return '';
  }
}

export function timeUntil(iso) {
  try {
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) return '';
    if (ms < 0) return 'overdue';
    var secs = Math.floor(ms / 1000);
    if (secs < 60) return 'in <1m';
    var mins = Math.floor(secs / 60);
    if (mins < 60) return 'in ' + mins + 'm';
    var hours = Math.floor(mins / 60);
    var remMins = mins % 60;
    if (hours < 24)
      return 'in ' + hours + 'h' + (remMins ? ' ' + remMins + 'm' : '');
    var days = Math.floor(hours / 24);
    return 'in ' + days + 'd ' + (hours % 24) + 'h';
  } catch (e) {
    return '';
  }
}

export function formatDuration(startIso, endIso) {
  try {
    const ms = new Date(endIso) - new Date(startIso);
    if (ms < 0 || isNaN(ms)) return '';
    const mins = Math.floor(ms / 60000);
    if (mins < 1) return '<1m';
    if (mins < 60) return mins + 'm';
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    if (hours < 24) return hours + 'h' + (remMins ? ' ' + remMins + 'm' : '');
    return Math.floor(hours / 24) + 'd ' + (hours % 24) + 'h';
  } catch (e) {
    return '';
  }
}

export function formatDate(iso) {
  try {
    const d = new Date(iso);
    return (
      d.toLocaleDateString('en-CA') +
      ' ' +
      d.toLocaleTimeString('en-CA', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    );
  } catch (e) {
    return iso;
  }
}

export function formatTime(iso) {
  try {
    const d = new Date(iso);
    return (
      d.toLocaleDateString('en-CA') +
      ' ' +
      d.toLocaleTimeString('en-CA', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    );
  } catch (e) {
    return '';
  }
}

export function openInEditor(filePath) {
  var dir = filePath.replace(/\/[^/]+$/, '');
  fetch('/api/terminal/run/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cmd: ['sh', '-c', '"${EDITOR:-vi}" "$1"', '--', filePath],
      cwd: dir,
    }),
  });
}

export function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
