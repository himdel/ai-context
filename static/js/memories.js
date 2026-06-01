import { esc, openInEditor } from '/js/utils.js';

let memoryListEl, mainEl, setActiveScreen, closeConversation, renderMarkdown, renderRichBlocks, RepoIdentity;
let getActiveMemoryId;

export function initMemories(deps) {
  memoryListEl = deps.memoryListEl;
  mainEl = deps.mainEl;
  setActiveScreen = deps.setActiveScreen;
  closeConversation = deps.closeConversation;
  renderMarkdown = deps.renderMarkdown;
  renderRichBlocks = deps.renderRichBlocks;
  RepoIdentity = deps.RepoIdentity;
  getActiveMemoryId = deps.getActiveMemoryId;
}

export function loadMemoriesSidebar() {
  fetch('/api/memories/')
    .then(r => r.json())
    .then(memoriesList => {
      memoryListEl.innerHTML = '';
      memoriesList.forEach(m => {
        var div = document.createElement('div');
        div.className = 'memory-item';
        div.dataset.id = m.id;
        if (m.id === getActiveMemoryId()) div.classList.add('active');

        var project = m.project ? m.project.replace(/^\/home\/[^/]+\//, '~/') : '';
        var mrid = m.project ? RepoIdentity.get(m.project) : null;
        var typeClass = m.type ? ' memory-type-' + m.type : '';
        div.innerHTML =
          '<div class="memory-info">' +
            (m.type ? '<span class="memory-type' + typeClass + '">' + esc(m.type) + '</span>' : '') +
            (project ? '<span>' + (mrid ? mrid.iconSm : '') + esc(project) + '</span>' : '') +
          '</div>' +
          '<div class="memory-name">' + esc(m.name) + '</div>';

        div.onclick = function() { loadMemory(m.id); };
        memoryListEl.appendChild(div);
      });
    });
}

export function showMemoriesHome() {
  fetch('/api/memories/')
    .then(r => r.json())
    .then(memoriesList => {
      var groups = {};
      var groupOrder = [];
      memoriesList.forEach(m => {
        var key = m.project || 'Other';
        if (!groups[key]) {
          groups[key] = [];
          groupOrder.push(key);
        }
        groups[key].push(m);
      });

      var container = document.getElementById('home-cols');
      if (!container) return;

      groupOrder.forEach(function(project) {
        var memories = groups[project];
        var isOther = project === 'Other';
        var short = isOther ? 'Other' : project.replace(/^\/home\/[^/]+\//, '~/');
        var name = isOther ? 'Other' : short.split('/').pop();

        var col = document.createElement('div');
        col.className = 'home-column';
        var mrid2 = !isOther ? RepoIdentity.get(project) : null;

        var header = document.createElement('div');
        header.className = 'home-column-header';
        if (mrid2) {
          header.style.background = mrid2.colorLight;
          col.style.borderTop = '3px solid ' + mrid2.colorBorder;
        }
        var nameDiv = document.createElement('div');
        nameDiv.innerHTML = (mrid2 ? mrid2.iconMd : '') + esc(name) + (!isOther ? '<span class="col-path">' + esc(short) + '</span>' : '');
        if (!isOther) nameDiv.title = project;
        header.appendChild(nameDiv);
        col.appendChild(header);

        var list = document.createElement('div');
        list.className = 'home-conv-list';

        memories.forEach(function(m) {
          var item = document.createElement('div');
          item.className = 'home-conv-item';
          var typeClass = m.type ? ' memory-type-' + m.type : '';
          var meta = '<div class="conv-meta">';
          if (m.type) meta += '<span class="memory-type' + typeClass + '">' + esc(m.type) + '</span>';
          meta += '</div>';
          item.innerHTML = meta + '<div>' + esc(m.name) + '</div>' +
            (m.description ? '<div style="font-size:11px;color:#888;margin-top:2px">' + esc(m.description) + '</div>' : '');
          item.onclick = function() { loadMemory(m.id); };
          list.appendChild(item);
        });

        col.appendChild(list);
        container.appendChild(col);
      });
    });
}

export function loadMemory(memoryId, pushHistory) {
  setActiveScreen({ activeMemoryId: memoryId });
  if (pushHistory !== false) {
    history.pushState({memoryId: memoryId}, '', '/memories/' + memoryId);
  }
  document.querySelectorAll('.memory-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === memoryId);
  });
  if (!memoryListEl.children.length) loadMemoriesSidebar();
  mainEl.innerHTML = '<div class="empty">Loading...</div>';

  fetch('/api/memories/' + memoryId + '/')
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        mainEl.innerHTML = '<div class="empty">' + esc(data.error) + '</div>';
        return;
      }

      mainEl.innerHTML = '';

      var toolbar = document.createElement('div');
      toolbar.className = 'conversation-toolbar';
      toolbar.innerHTML = '<span class="header-btns"><span class="close-conv" title="Close">&times;</span></span>';
      toolbar.querySelector('.close-conv').onclick = function() { closeConversation('memory'); };
      mainEl.appendChild(toolbar);

      var header = document.createElement('div');
      header.className = 'conversation-header';
      header.style.borderLeft = '3px solid #d97706';
      header.style.paddingLeft = '12px';
      var project = data.project ? data.project.replace(/^\/home\/[^/]+\//, '~/') : '';
      var typeClass = data.type ? ' memory-type-' + data.type : '';
      header.innerHTML =
        '<span>' + esc(data.name) + '</span>' +
        (data.type ? '<span class="memory-type' + typeClass + '">' + esc(data.type) + '</span>' : '') +
        (project ? '<span>' + esc(project) + '</span>' : '') +
        (data.conversation_id ? '<span>origin: <a href="/conversations/' + esc(data.conversation_id) + '" style="color:#4338ca">' + esc(data.conversation_id.substring(0, 8)) + '...</a></span>' : '') +
        '<span style="font-family:monospace;font-size:11px">' + esc(data.path) + '</span>';
      mainEl.appendChild(header);

      if (data.type === 'index') {
        var note = document.createElement('div');
        note.style.cssText = 'background:#fefce8;border:1px solid #ca8a04;border-radius:6px;padding:8px 12px;margin:8px 0;font-size:12px;color:#854d0e';
        note.textContent = 'This is the memory index — the only file loaded into context by default. Claude uses the descriptions here to decide which memories to read in full, so keeping them accurate and specific is important.';
        mainEl.appendChild(note);
      } else {
        var indexPath = data.path.replace(/\/[^/]+$/, '/MEMORY.md');
        var indexId = btoa(indexPath).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        var backLink = document.createElement('a');
        backLink.href = '/memories/' + indexId;
        backLink.textContent = '← Memory Index';
        backLink.style.cssText = 'display:inline-block;margin:8px 0;font-size:12px;color:#854d0e;text-decoration:none';
        backLink.onclick = function(e) { e.preventDefault(); loadMemory(indexId); };
        mainEl.appendChild(backLink);
      }

      var view = document.createElement('div');
      view.className = 'memory-detail-view';

      var actions = document.createElement('div');
      actions.className = 'memory-actions';

      var contentBlock = document.createElement('div');
      contentBlock.className = 'block text';

      var renderContent = function() {
        var displayText = data.content;
        if (displayText.startsWith('---')) {
          var end = displayText.indexOf('\n---', 3);
          if (end !== -1) displayText = displayText.substring(end + 4).trim();
        }
        contentBlock.innerHTML = renderMarkdown(displayText);

        if (data.type === 'index') {
          var memoryDir = data.path.replace(/\/[^/]+$/, '/');
          contentBlock.querySelectorAll('a[href$=".md"]').forEach(function(a) {
            var href = a.getAttribute('href');
            if (/^https?:\/\//.test(href)) return;
            var absPath = memoryDir + href;
            var id = btoa(absPath).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
            a.href = '/memories/' + id;
            a.removeAttribute('target');
            a.removeAttribute('rel');
            a.onclick = function(e) { e.preventDefault(); loadMemory(id); };
          });
        }
      };
      renderContent();

      var editBtn = document.createElement('button');
      editBtn.textContent = 'Edit';
      editBtn.onclick = function() {
        contentBlock.innerHTML = '';
        var textarea = document.createElement('textarea');
        textarea.className = 'skill-edit-area';
        textarea.value = data.content;
        contentBlock.appendChild(textarea);

        actions.innerHTML = '';
        var saveBtn = document.createElement('button');
        saveBtn.textContent = 'Save';
        saveBtn.onclick = function() {
          saveBtn.textContent = '...';
          fetch('/api/memories/' + memoryId + '/', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content: textarea.value})
          })
          .then(r => r.json().then(d => ({ok: r.ok, data: d})))
          .then(function(resp) {
            if (resp.ok) {
              loadMemory(memoryId, false);
            } else {
              saveBtn.textContent = 'Error';
              setTimeout(function() { saveBtn.textContent = 'Save'; }, 2000);
            }
          });
        };
        actions.appendChild(saveBtn);

        var cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancel';
        cancelBtn.onclick = function() { loadMemory(memoryId, false); };
        actions.appendChild(cancelBtn);
      };
      actions.appendChild(editBtn);

      var editorBtn = document.createElement('button');
      editorBtn.textContent = '$EDITOR';
      editorBtn.onclick = function() {
        openInEditor(data.path);
      };
      actions.appendChild(editorBtn);

      var deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.style.color = '#dc2626';
      deleteBtn.style.borderColor = '#fca5a5';
      deleteBtn.onclick = function() {
        if (!confirm('Delete memory "' + data.name + '"?')) return;
        fetch('/api/memories/' + memoryId + '/', {method: 'DELETE'})
          .then(function() {
            loadMemoriesSidebar();
            closeConversation('memory');
          });
      };
      if (data.type !== 'index') actions.appendChild(deleteBtn);

      view.appendChild(actions);

      if (data.content && data.content.startsWith('---')) {
        var fmMatch = data.content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
        if (fmMatch) {
          var fmBlock = document.createElement('dl');
          fmBlock.className = 'skill-frontmatter';
          var fmLines = fmMatch[1].split('\n');
          var currentKey = '';
          var currentVal = '';
          var flush = function() {
            if (!currentKey) return;
            var dt = document.createElement('dt');
            dt.textContent = currentKey;
            var dd = document.createElement('dd');
            dd.textContent = currentVal.trim();
            fmBlock.appendChild(dt);
            fmBlock.appendChild(dd);
          };
          fmLines.forEach(function(line) {
            var kv = line.match(/^([a-zA-Z_-]+)\s*:\s*(.*)$/);
            if (kv && !line.match(/^\s/)) {
              flush();
              currentKey = kv[1];
              currentVal = kv[2].replace(/^>-?\s*$/, '');
            } else {
              currentVal += ' ' + line.trim();
            }
          });
          flush();
          view.appendChild(fmBlock);
        }
      }

      view.appendChild(contentBlock);
      mainEl.appendChild(view);
      renderRichBlocks();
      mainEl.scrollTop = 0;
      mainEl.focus();
    });
}
