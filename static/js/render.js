import { esc, loadScript, loadCSS } from '/js/utils.js';
import { linkifyForge } from '/js/forge.js';

let mainEl, mainWrapEl;

export function initRender(deps) {
  mainEl = deps.mainEl;
  mainWrapEl = deps.mainWrapEl;
}

var _depsCache = {};
function loadRichDeps(lang) {
  var key = (lang === 'graphviz') ? 'dot' : lang;
  if (!_depsCache[key]) {
    if (key === 'mermaid') {
      _depsCache[key] = loadScript('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js')
        .then(function() { mermaid.initialize({ startOnLoad: false, theme: 'default' }); });
    } else if (key === 'math') {
      _depsCache[key] = Promise.all([
        loadCSS('https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.css'),
        loadScript('https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.js'),
      ]);
    } else if (key === 'dot') {
      _depsCache[key] = loadScript('https://cdn.jsdelivr.net/npm/@viz-js/viz@3/lib/viz-standalone.js');
    } else if (key === 'vega-lite') {
      _depsCache[key] = loadScript('https://cdn.jsdelivr.net/npm/vega@5')
        .then(function() { return loadScript('https://cdn.jsdelivr.net/npm/vega-lite@5'); })
        .then(function() { return loadScript('https://cdn.jsdelivr.net/npm/vega-embed@6'); });
    } else if (key === 'geojson') {
      _depsCache[key] = Promise.all([
        loadCSS('https://cdn.jsdelivr.net/npm/leaflet@1/dist/leaflet.css'),
        loadScript('https://cdn.jsdelivr.net/npm/leaflet@1/dist/leaflet.js'),
      ]);
    } else if (key === 'abc') {
      _depsCache[key] = Promise.all([
        loadScript('https://cdn.jsdelivr.net/npm/abcjs@6/dist/abcjs-basic-min.js'),
        loadCSS('https://cdn.jsdelivr.net/npm/abcjs@6/abcjs-audio.css'),
      ]);
    } else if (key === 'markmap') {
      _depsCache[key] = loadScript('https://cdn.jsdelivr.net/npm/d3@7')
        .then(function() { return loadScript('https://cdn.jsdelivr.net/npm/markmap-lib@0.18/dist/browser/index.iife.js'); })
        .then(function() { return loadScript('https://cdn.jsdelivr.net/npm/markmap-view@0.18/dist/browser/index.js'); });
    } else if (key === 'plantuml') {
      _depsCache[key] = loadScript('https://cdn.jsdelivr.net/npm/pako@2/dist/pako.min.js');
    } else {
      _depsCache[key] = Promise.resolve();
    }
  }
  return _depsCache[key];
}

var richBlockCounter = 0;
var richLangs = ['mermaid', 'math', 'dot', 'graphviz', 'vega-lite', 'geojson', 'abc', 'markmap', 'plantuml'];

marked.use({
  renderer: {
    code: function(token) {
      var lang = (token.lang || '').toLowerCase();
      if (richLangs.indexOf(lang) === -1) return false;
      var id = 'rich-' + (richBlockCounter++);
      var escaped = token.text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      return '<div class="rich-container">' +
        '<div class="rich-toolbar"><button class="rich-toggle" title="Toggle source">Source</button></div>' +
        '<div class="rich-rendered" data-rich-id="' + id + '" data-rich-lang="' + lang + '" data-rich-src="' + encodeURIComponent(token.text) + '"></div>' +
        '<pre class="rich-source" style="display:none"><code>' + escaped + '</code></pre>' +
        '</div>';
    }
  }
});

export function renderRichBlocks() {
  document.querySelectorAll('.rich-rendered[data-rich-src]:not(.rich-done)').forEach(function(el) {
    el.classList.add('rich-done');
    var src = decodeURIComponent(el.getAttribute('data-rich-src'));
    var id = el.getAttribute('data-rich-id');
    var lang = el.getAttribute('data-rich-lang');

    loadRichDeps(lang).then(function() {
      if (lang === 'mermaid') {
        mermaid.render(id, src).then(function(result) {
          el.innerHTML = result.svg;
        }).catch(function() {
          el.innerHTML = '<em style="color:#999">Failed to render diagram</em>';
        });

      } else if (lang === 'math') {
        try {
          katex.render(src.trim(), el, { displayMode: true, throwOnError: false });
        } catch(e) {
          el.innerHTML = '<em style="color:#999">Failed to render math</em>';
        }

      } else if (lang === 'dot' || lang === 'graphviz') {
        Viz.instance().then(function(viz) {
          try {
            el.innerHTML = viz.renderSVGElement(src).outerHTML;
          } catch(e) {
            el.innerHTML = '<em style="color:#999">Failed to render graph</em>';
          }
        }).catch(function() {
          el.innerHTML = '<em style="color:#999">Failed to render graph</em>';
        });

      } else if (lang === 'vega-lite') {
        try {
          var spec = JSON.parse(src);
          vegaEmbed(el, spec, { actions: false }).catch(function() {
            el.innerHTML = '<em style="color:#999">Failed to render chart</em>';
          });
        } catch(e) {
          el.innerHTML = '<em style="color:#999">Invalid Vega-Lite JSON</em>';
        }

      } else if (lang === 'geojson') {
        try {
          var geojson = JSON.parse(src);
          var mapDiv = document.createElement('div');
          mapDiv.className = 'rich-map';
          el.appendChild(mapDiv);
          var map = L.map(mapDiv);
          L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap'
          }).addTo(map);
          var layer = L.geoJSON(geojson).addTo(map);
          var bounds = layer.getBounds();
          map.fitBounds(bounds, { padding: [20, 20] });
          var ResetControl = L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function() {
              var btn = L.DomUtil.create('a', 'leaflet-control-zoom-reset');
              btn.innerHTML = '&#x21ba;';
              btn.title = 'Reset view';
              btn.href = '#';
              btn.setAttribute('role', 'button');
              L.DomEvent.disableClickPropagation(btn);
              L.DomEvent.on(btn, 'click', function(e) {
                L.DomEvent.preventDefault(e);
                map.fitBounds(bounds, { padding: [20, 20] });
              });
              return btn;
            },
          });
          map.addControl(new ResetControl());
        } catch(e) {
          el.innerHTML = '<em style="color:#999">Failed to render map</em>';
        }

      } else if (lang === 'abc') {
        var abcDiv = document.createElement('div');
        abcDiv.className = 'abcjs-container';
        el.appendChild(abcDiv);
        var audioDiv = document.createElement('div');
        audioDiv.className = 'abcjs-audio';
        el.appendChild(audioDiv);
        try {
          var visualObj = ABCJS.renderAbc(abcDiv, src);
          if (ABCJS.synth && ABCJS.synth.supportsAudio()) {
            var synthControl = new ABCJS.synth.SynthController();
            synthControl.load(audioDiv, null, {
              displayPlay: true,
              displayProgress: true,
              displayRestart: true,
            });
            synthControl.setTune(visualObj[0], false);
          }
        } catch(e) {
          el.innerHTML = '<em style="color:#999">Failed to render notation</em>';
        }

      } else if (lang === 'markmap') {
        try {
          var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          svg.setAttribute('style', 'width:100%;height:300px');
          el.appendChild(svg);
          var transformer = new markmap.Transformer();
          var parsed = transformer.transform(src);
          markmap.Markmap.create(svg, null, parsed.root);
        } catch(e) {
          el.innerHTML = '<em style="color:#999">Failed to render mind map</em>';
        }

      } else if (lang === 'plantuml') {
        var encoded = plantumlEncode(src);
        var img = document.createElement('img');
        img.src = 'https://www.plantuml.com/plantuml/svg/' + encoded;
        img.alt = 'PlantUML diagram';
        img.onerror = function() {
          el.innerHTML = '<em style="color:#999">Failed to render PlantUML diagram</em>';
        };
        el.appendChild(img);
      }
    }).catch(function() {
      el.innerHTML = '<em style="color:#999">Failed to load rendering library</em>';
    });
  });
}

function plantumlEncode(text) {
  function encode6bit(b) {
    if (b < 10) return String.fromCharCode(48 + b);
    b -= 10;
    if (b < 26) return String.fromCharCode(65 + b);
    b -= 26;
    if (b < 26) return String.fromCharCode(97 + b);
    b -= 26;
    if (b === 0) return '-';
    if (b === 1) return '_';
    return '?';
  }
  function append3bytes(b1, b2, b3) {
    var c1 = b1 >> 2;
    var c2 = ((b1 & 0x3) << 4) | (b2 >> 4);
    var c3 = ((b2 & 0xF) << 2) | (b3 >> 6);
    var c4 = b3 & 0x3F;
    return encode6bit(c1 & 0x3F) + encode6bit(c2 & 0x3F) + encode6bit(c3 & 0x3F) + encode6bit(c4 & 0x3F);
  }
  var data = new TextEncoder().encode(text);
  var deflated = new Uint8Array(pako.deflateRaw(data));
  var r = '';
  for (var i = 0; i < deflated.length; i += 3) {
    if (i + 2 === deflated.length) {
      r += append3bytes(deflated[i], deflated[i + 1], 0);
    } else if (i + 1 === deflated.length) {
      r += append3bytes(deflated[i], 0, 0);
    } else {
      r += append3bytes(deflated[i], deflated[i + 1], deflated[i + 2]);
    }
  }
  return r;
}

export function initAutolinks() {
  fetch('/api/autolinks/')
    .then(r => r.json())
    .then(autolinks => {
      if (!autolinks.length) return;
      const reEscape = s => s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
      const extensions = autolinks.map(al => {
        const name = 'autolink-' + al.prefix;
        const pre = reEscape(al.prefix);
        return {
          name: name,
          level: 'inline',
          start: function(src) { return src.match(new RegExp(pre))?.index; },
          tokenizer: function(src) {
            const match = src.match(new RegExp('^(' + pre + '(\\d+))'));
            if (match) {
              return { type: name, raw: match[0], text: match[1], id: match[2], url: al.url.replace('{id}', match[2]) };
            }
          },
          renderer: function(token) {
            return '<a href="' + esc(token.url) + '" target="_blank" rel="noopener noreferrer">' + esc(token.text) + '</a>';
          },
        };
      });
      marked.use({ extensions: extensions });
    });
}

export function renderMarkdown(text) {
  if (!text) return '';
  var html = linkifyForge(marked.parse(text));
  html = html.replace(/<command-message>([^<]*)<\/command-message>\s*<command-name>\/?([^<]+)<\/command-name>/g, function(match, msg, name) {
    if (!/^[\w][\w.-]*$/.test(name)) return match;
    return '<a href="#" class="skill-link" data-skill="' + esc(name) + '" title="' + esc(msg) + '">/' + esc(name) + '</a>';
  });
  html = html.replace(/<command-message>[^<]*<\/command-message>\n?/g, '');
  html = html.replace(/<command-name>\/?([^<]+)<\/command-name>/g, function(match, name) {
    if (!/^[\w][\w.-]*$/.test(name)) return match;
    return '<a href="#" class="skill-link" data-skill="' + esc(name) + '">/' + esc(name) + '</a>';
  });
  html = html.replace(/<\/?command-args>/g, '');
  return html;
}

function formatJson(str) {
  var trimmed = str.trim();
  if (!(trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[')) return null;
  try {
    var obj = JSON.parse(trimmed);
    var pretty = JSON.stringify(obj, null, 2);
    return pretty.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"([^"\\]*(\\.[^"\\]*)*)"(\s*:)/g, '<span style="color:#881280">"$1"</span>$3')
      .replace(/:\s*"([^"\\]*(\\.[^"\\]*)*)"/g, ': <span style="color:#1a7f37">"$1"</span>')
      .replace(/:\s*(\d+\.?\d*)/g, ': <span style="color:#0550ae">$1</span>')
      .replace(/:\s*(true|false|null)/g, ': <span style="color:#cf222e">$1</span>');
  } catch (e) {
    return null;
  }
}

export var taskSubjects = {};

function extractTaskStates(messages) {
  var tasks = {};
  messages.forEach(function(m) {
    m.content.forEach(function(block) {
      if (block.type !== 'tool_use') return;
      if (block.name === 'TaskCreate' && block.result) {
        var tm = block.result.match(/Task #(\d+) created successfully: (.+)/);
        if (tm) {
          tasks[tm[1]] = { id: tm[1], subject: block.input.subject || tm[2], status: 'pending' };
        }
      }
      if (block.name === 'TaskUpdate' && block.input && block.input.taskId) {
        var t = tasks[block.input.taskId];
        if (t) {
          if (block.input.status) t.status = block.input.status;
          if (block.input.subject) t.subject = block.input.subject;
        }
      }
    });
  });
  var counts = { pending: 0, in_progress: 0, completed: 0, total: 0 };
  for (var id in tasks) {
    if (tasks[id].status === 'deleted') continue;
    counts.total++;
    if (counts[tasks[id].status] !== undefined) counts[tasks[id].status]++;
  }
  return { tasks: tasks, counts: counts };
}

function extractRunningAgents(messages) {
  var running = [];
  messages.forEach(function(m) {
    m.content.forEach(function(block) {
      if (block.type === 'tool_use' && block.name === 'Agent') {
        if (!block.subagent && (block.result == null || (typeof block.result === 'string' && block.result.indexOf('Async agent launched') === 0))) {
          running.push({
            description: block.input ? block.input.description || '' : '',
            type: block.input ? block.input.subagent_type || '' : ''
          });
        }
      }
    });
  });
  return running;
}

function scrollToBlock(selector) {
  var els = mainEl.querySelectorAll(selector);
  var el = els.length ? els[els.length - 1] : null;
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.style.outline = '2px solid #4338ca';
    setTimeout(function() { el.style.outline = ''; }, 2000);
  }
}

function buildStatusBar(messages) {
  var taskState = extractTaskStates(messages);
  var agents = extractRunningAgents(messages);
  if (taskState.counts.total === 0 && agents.length === 0) return null;

  var bar = document.createElement('div');
  bar.className = 'conversation-status-bar';

  if (taskState.counts.total > 0) {
    var tasksEl = document.createElement('div');
    tasksEl.className = 'status-bar-tasks';
    var label = document.createElement('span');
    label.className = 'status-bar-label';
    label.textContent = 'Tasks:';
    tasksEl.appendChild(label);
    var taskIds = Object.keys(taskState.tasks).sort(function(a, b) { return a - b; });
    taskIds.forEach(function(id) {
      var t = taskState.tasks[id];
      if (t.status === 'deleted') return;
      var item = document.createElement('span');
      item.className = 'status-bar-task ' + t.status;
      item.textContent = '#' + id + ' ' + t.subject;
      item.title = '#' + id + ' [' + t.status.replace('_', ' ') + '] ' + t.subject;
      item.onclick = function() {
        scrollToBlock('[data-task-id="' + id + '"]');
      };
      tasksEl.appendChild(item);
    });
    bar.appendChild(tasksEl);
  }

  if (taskState.counts.total > 0 && agents.length > 0) {
    var sep = document.createElement('span');
    sep.className = 'status-bar-separator';
    bar.appendChild(sep);
  }

  if (agents.length > 0) {
    var agentsEl = document.createElement('div');
    agentsEl.className = 'status-bar-agents';
    var alabel = document.createElement('span');
    alabel.className = 'status-bar-label';
    alabel.textContent = 'Agents:';
    agentsEl.appendChild(alabel);
    agents.forEach(function(a) {
      var pill = document.createElement('span');
      pill.className = 'status-bar-agent';
      var desc = a.description || a.type || 'Agent';
      pill.textContent = desc;
      pill.title = (a.type ? a.type + ': ' : '') + (a.description || '');
      pill.onclick = function() {
        scrollToBlock('[data-agent-desc="' + CSS.escape(desc) + '"]');
      };
      agentsEl.appendChild(pill);
    });
    bar.appendChild(agentsEl);
  }

  return bar;
}

export function updateStatusBar(messages) {
  var existing = mainWrapEl.querySelector('.conversation-status-bar');
  if (existing) existing.remove();
  if (!messages) return;
  var bar = buildStatusBar(messages);
  if (bar) mainWrapEl.appendChild(bar);
}

function renderToolInput(name, input) {
  var main = null;
  var skip = [];
  if (name === 'Read') {
    skip = ['file_path', 'offset', 'limit'];
    main = '<div class="edit-file">' + esc(input.file_path || '') + '</div>' +
      (input.offset || input.limit ? '<span style="color:#888;font-size:11px">' +
        (input.offset ? ':' + input.offset : '') +
        (input.limit ? ' (' + input.limit + ' lines)' : '') +
      '</span>' : '');
  }
  if (name === 'Bash') {
    skip = ['command', 'description'];
    const desc = input.description ? '<div style="color:#888;font-size:11px">' + esc(input.description) + '</div>' : '';
    main = desc + '<code>' + esc(input.command || '') + '</code>';
  }
  if (name === 'Agent') {
    var label = 'Agent';
    if (input.subagent_type) label += ' <span class="agent-type">' + esc(input.subagent_type) + '</span>';
    var html = '<div class="agent-header">' + label + '</div>';
    if (input.description) html += '<div class="agent-desc">' + esc(input.description) + '</div>';
    if (input.prompt) html += '<div class="agent-prompt">' + renderMarkdown(input.prompt) + '</div>';
    var extra = {};
    var hasExtra = false;
    var skip = ['description', 'subagent_type', 'prompt'];
    for (var k in input) { if (skip.indexOf(k) === -1) { extra[k] = input[k]; hasExtra = true; } }
    if (hasExtra) html += '<div style="margin-top:6px;color:#888;font-size:11px">' + esc(JSON.stringify(extra, null, 2)) + '</div>';
    return html;
  }
  if (name === 'Edit') {
    var header = '<div class="edit-file">' + esc(input.file_path || '') +
      (input.replace_all ? ' <span class="edit-flag">(replace all)</span>' : '') +
      '</div>';
    var old_s = input.old_string || '';
    var new_s = input.new_string || '';
    var diff = '<div class="edit-diff">';
    if (old_s) diff += '<div class="edit-old">' + esc(old_s) + '</div>';
    if (new_s) diff += '<div class="edit-new">' + esc(new_s) + '</div>';
    diff += '</div>';
    return header + diff;
  }
  if (name === 'ExitPlanMode') {
    var html = '';
    if (input.plan) {
      html += '<div class="plan-content">' + renderMarkdown(input.plan) + '</div>';
    }
    if (input.allowedPrompts && input.allowedPrompts.length) {
      html += '<div class="plan-prompts"><div class="plan-prompts-label">Allowed prompts:</div>';
      input.allowedPrompts.forEach(function(p) {
        html += '<div class="plan-prompt"><span class="plan-prompt-tool">' + esc(p.tool) + '</span> ' + esc(p.prompt) + '</div>';
      });
      html += '</div>';
    }
    if (input.planFilePath) {
      var planId = input.planFilePath.split('/').pop().replace(/\.md$/, '');
      html += '<div class="plan-file"><a href="/plans/' + esc(planId) + '" style="color:#6d28d9">' + esc(input.planFilePath) + '</a></div>';
    }
    return html || esc(JSON.stringify(input, null, 2));
  }
  if (name === 'EnterPlanMode') {
    return '<em>Entering plan mode...</em>';
  }
  if (name === 'Grep') {
    skip = ['pattern', 'path', 'head_limit', 'output_mode', '-A', '-B', '-C'];
    main = '<code>grep</code> <code>' + esc(input.pattern || '') + '</code>' +
      (input.path ? ' ' + esc(input.path) : '');
  }
  if (name === 'Glob') {
    skip = ['pattern'];
    main = '<code>' + esc(input.pattern || '') + '</code>';
  }
  if (name === 'Write') {
    var header = '<div class="edit-file">' + esc(input.file_path || '') + '</div>';
    var content = input.content || '';
    var lines = content.split('\n').length;
    var label = lines + ' line' + (lines === 1 ? '' : 's');
    return header + '<details class="write-content"><summary style="color:#888;font-size:11px;cursor:pointer">' + esc(label) + '</summary>' +
      '<pre style="margin:4px 0 0;background:#dfd;padding:6px 8px;border-radius:3px;max-height:300px;overflow-y:auto;white-space:pre-wrap">' + esc(content) + '</pre></details>';
  }
  if (name === 'TaskUpdate') {
    skip = ['taskId', 'status', 'activeForm'];
    var scolor = input.status === 'completed' ? '#15803d' : input.status === 'in_progress' ? '#b45309' : '#555';
    var sbg = input.status === 'completed' ? '#dcfce7' : input.status === 'in_progress' ? '#fef3c7' : '#f0f0f0';
    main = '#' + esc(input.taskId || '?');
    if (input.status) main += ' <span style="background:' + sbg + ';color:' + scolor + ';padding:1px 6px;border-radius:3px;font-size:11px">' + esc(input.status) + '</span>';
    var subj = taskSubjects[input.taskId];
    if (subj) main += ' <span style="color:#888">' + esc(subj) + '</span>';
  }
  if (name === 'TaskCreate') {
    skip = ['subject', 'description', 'activeForm'];
    var tid = '';
    for (var k in taskSubjects) { if (taskSubjects[k] === input.subject) { tid = k; break; } }
    main = (tid ? '#' + esc(tid) + ' ' : '') + '<strong>' + esc(input.subject || '') + '</strong>';
    if (input.description) main += '<div style="color:#888;font-size:11px;margin-top:2px">' + esc(input.description) + '</div>';
  }
  if (name === 'AskUserQuestion') {
    var html = '';
    var questions = input.questions || [];
    questions.forEach(function(q) {
      if (q.header) html += '<div style="font-weight:600;color:#4338ca;margin-bottom:2px">' + esc(q.header) + '</div>';
      html += '<div style="margin-bottom:4px">' + esc(q.question || '') + '</div>';
      if (q.options && q.options.length) {
        html += '<div style="margin-left:8px;font-size:11px;color:#888">';
        q.options.forEach(function(o) {
          html += '<div>&#8226; <strong>' + esc(o.label) + '</strong>' +
            (o.description ? ' &mdash; ' + esc(o.description) : '') + '</div>';
        });
        html += '</div>';
      }
    });
    return html || esc(JSON.stringify(input, null, 2));
  }
  if (name === 'WebFetch') {
    skip = ['url', 'prompt'];
    main = '<a href="' + esc(input.url || '') + '" target="_blank" rel="noopener noreferrer" style="color:#4338ca">' + esc(input.url || '') + '</a>';
    if (input.prompt) main += '<div style="color:#888;font-size:11px;margin-top:2px">' + esc(input.prompt) + '</div>';
  }
  if (name === 'WebSearch') {
    skip = ['query'];
    main = '<code>' + esc(input.query || '') + '</code>';
  }
  if (main === null && name.indexOf('mcp__') === 0) {
    skip = ['cloudId', 'responseContentFormat', 'contentFormat'];
    if (input.issueIdOrKey) {
      skip.push('issueIdOrKey');
      main = '<strong>' + esc(input.issueIdOrKey) + '</strong>';
      if (input.summary) { skip.push('summary'); main += ' ' + esc(input.summary); }
    } else if (input.jql) {
      skip.push('jql');
      main = '<code>' + esc(input.jql) + '</code>';
    } else if (input.summary) {
      skip.push('summary');
      main = (input.projectKey ? esc(input.projectKey) + ': ' : '') + '<strong>' + esc(input.summary) + '</strong>';
      if (input.projectKey) skip.push('projectKey');
    } else if (input.query) {
      skip.push('query');
      main = '<code>' + esc(input.query) + '</code>';
    } else {
      main = '';
    }
  }
  if (main === null) return formatJson(JSON.stringify(input)) || esc(JSON.stringify(input, null, 2));
  var extra = {};
  var hasExtra = false;
  for (var k in input) { if (skip.indexOf(k) === -1) { extra[k] = input[k]; hasExtra = true; } }
  if (hasExtra) main += '\n' + esc(JSON.stringify(extra, null, 2));
  return main;
}

function blockToMarkdown(block) {
  if (block.type === 'text') return block.text || '';
  if (block.type === 'thinking') return '<thinking>\n' + (block.text || '') + '\n</thinking>';
  if (block.type === 'tool_use') {
    if (block.name === 'Skill' && block.input && block.input.skill) {
      var md = '**/' + block.input.skill + '**';
      var extra = {};
      var hasExtra = false;
      for (var k in block.input) { if (k !== 'skill') { extra[k] = block.input[k]; hasExtra = true; } }
      if (hasExtra) md += '\n```json\n' + JSON.stringify(extra, null, 2) + '\n```';
      return md;
    }
    var md = '**' + (block.name || 'Tool') + '**';
    if (block.input) md += '\n```json\n' + JSON.stringify(block.input, null, 2) + '\n```';
    if (block.result) md += '\n**output**\n```\n' + block.result + '\n```';
    if (block.subagent) md += '\n\n' + subagentToMarkdown(block.subagent);
    return md;
  }
  return '';
}

function subagentToMarkdown(sub) {
  var label = (sub.agent_type || 'Agent') + (sub.description ? ': ' + sub.description : '');
  var md = '> **' + label + '**\n';
  sub.messages.forEach(function(m) {
    md += '>\n> **' + m.role + '**\n';
    m.content.forEach(function(block) {
      md += '> ' + blockToMarkdown(block).replace(/\n/g, '\n> ') + '\n';
    });
  });
  return md;
}

export function messageToMarkdown(msgEl) {
  var msg = msgEl._messageData;
  if (!msg) return '';
  var parts = [];
  msg.content.forEach(function(block) {
    var md = blockToMarkdown(block);
    if (md) parts.push(md);
  });
  return parts.join('\n\n');
}

function renderToolResult(block) {
  if (!block.result && !block.subagent) return '';
  var useMarkdown = block.subagent || block.name === 'ExitPlanMode';
  var html = '';

  if (block.subagent) {
    html += renderSubagent(block.subagent);
  }
  if (block.result) {
    var resultBody = useMarkdown
      ? renderMarkdown(block.result)
      : (formatJson(block.result) || esc(block.result));
    if (useMarkdown) {
      html += '<details class="agent-result"><summary>output <span class="expand-all" title="Expand/collapse all">&#x29C9;</span></summary>' +
        '<div class="agent-result-body">' + resultBody + '</div></details>';
    } else {
      html += '<details class="tool-result-inline"><summary>output <span class="expand-all" title="Expand/collapse all">&#x29C9;</span></summary>' +
        '<div class="tool-output">' + resultBody + '</div></details>';
    }
  }

  return html;
}

function isSkillTrigger(m) {
  if (!m) return false;
  if (m.role === 'user' && m.content.some(b => b.type === 'text' && /<command-name>/.test(b.text))) return true;
  if (m.role === 'assistant' && m.content.some(b => b.type === 'tool_use' && b.name === 'Skill')) return true;
  return false;
}

export function isSkillPrompt(m, prev) {
  if (!m || m.role !== 'user') return false;
  if (!m.content.every(b => b.type === 'text')) return false;
  return isSkillTrigger(prev);
}

export function renderSkillPrompt(m) {
  var body = m.content.map(b => renderMarkdown(b.text)).join('');
  return '<details class="skill-prompt-details"><summary>Skill prompt</summary>' +
    '<div class="skill-prompt-body">' + body + '</div></details>';
}

export function renderBlock(block) {
  if (block.type === 'text') {
    return '<div class="block text">' + renderMarkdown(block.text) + '</div>';
  }
  if (block.type === 'thinking') {
    return '<details class="block thinking"><summary>Thinking... <span class="expand-all" title="Expand/collapse all">&#x29C9;</span></summary>' + renderMarkdown(block.text) + '</details>';
  }
  if (block.type === 'tool_use') {
    var result = renderToolResult(block);
    if (block.name === 'ExitPlanMode') {
      return '<div class="block plan-block">' +
        '<div class="plan-header">Plan</div>' +
        renderToolInput(block.name, block.input) +
        result + '</div>';
    }
    if (block.name === 'EnterPlanMode') {
      return '<div class="block plan-enter">' + renderToolInput(block.name, block.input) + result + '</div>';
    }
    if (block.name === 'Skill' && block.input && block.input.skill) {
      var sn = block.input.skill;
      var extra = {};
      var hasExtra = false;
      for (var k in block.input) { if (k !== 'skill') { extra[k] = block.input[k]; hasExtra = true; } }
      return '<div class="block tool_use">' +
        '<div class="tool-name">Skill</div>' +
        '<div class="tool-input">' +
          '<a href="#" class="skill-link" data-skill="' + esc(sn) + '" title="View skill /' + esc(sn) + '">/' + esc(sn) + '</a>' +
          (hasExtra ? '\n' + esc(JSON.stringify(extra, null, 2)) : '') +
        '</div>' + result + '</div>';
    }
    var attrs = '';
    if (block.name === 'TaskCreate' && block.input && block.input.subject) {
      attrs = ' data-task-subject="' + esc(block.input.subject) + '"';
    }
    if (block.name === 'TaskUpdate' && block.input && block.input.taskId) {
      attrs = ' data-task-id="' + esc(block.input.taskId) + '"';
    }
    if (block.name === 'Agent' && block.input) {
      attrs = ' data-agent-desc="' + esc(block.input.description || block.input.subagent_type || 'Agent') + '"';
    }
    return '<div class="block tool_use"' + attrs + '>' +
      '<div class="tool-name">' + esc(block.name) + '</div>' +
      '<div class="tool-input">' + renderToolInput(block.name, block.input) + '</div>' +
      result + '</div>';
  }
  return '';
}

function renderSubagent(sub) {
  var label = (sub.agent_type || 'Agent') + (sub.description ? ': ' + sub.description : '');
  var html = '<details class="subagent"><summary>' + esc(label) + ' <span class="expand-all" title="Expand/collapse all">&#x29C9;</span></summary>';
  html += '<div class="subagent-messages">';
  sub.messages.forEach(function(m) {
    html += '<div class="message ' + m.role + '">';
    html += '<div class="role">' + esc(m.role) + '</div>';
    m.content.forEach(function(block) {
      html += renderBlock(block);
    });
    html += '</div>';
  });
  html += '</div></details>';
  return html;
}
