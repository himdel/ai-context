import { esc, openInEditor } from '/js/utils.js';
import { renderMarkdown, renderRichBlocks } from '/js/render.js';

let repoListEl, mainEl, setActiveScreen, closeConversation, RepoIdentity;
let getActiveRepoPath;

export function initRepos(deps) {
  repoListEl = deps.repoListEl;
  mainEl = deps.mainEl;
  setActiveScreen = deps.setActiveScreen;
  closeConversation = deps.closeConversation;
  RepoIdentity = deps.RepoIdentity;
  getActiveRepoPath = deps.getActiveRepoPath;
}

export function loadReposSidebar() {
  fetch('/api/repos/')
    .then(r => r.json())
    .then(repos => {
      repoListEl.innerHTML = '';
      repos.forEach(repo => {
        var div = document.createElement('div');
        div.className = 'repo-item';
        div.dataset.path = repo;
        if (repo === getActiveRepoPath()) div.classList.add('active');

        var short = repo.replace(/^\/home\/[^/]+\//, '~/');
        var name = short.split('/').pop();
        var rid = RepoIdentity.get(repo);
        div.innerHTML =
          '<div class="repo-name">' + (rid ? rid.iconSm : '') + esc(name) + '</div>' +
          '<div class="repo-path">' + esc(short) + '</div>';

        div.onclick = function() { loadRepo(repo); };
        repoListEl.appendChild(div);
      });
    });
}

export function showReposHome() {
  fetch('/api/repos/')
    .then(r => r.json())
    .then(repos => {
      var container = document.getElementById('home-cols');
      if (!container) return;

      repos.forEach(function(repo) {
        var short = repo.replace(/^\/home\/[^/]+\//, '~/');
        var name = short.split('/').pop();
        var rid = RepoIdentity.get(repo);

        var col = document.createElement('div');
        col.className = 'home-column';
        if (rid) col.style.borderTop = '3px solid ' + rid.colorBorder;

        var header = document.createElement('div');
        header.className = 'home-column-header';
        if (rid) header.style.background = rid.colorLight;
        var nameDiv = document.createElement('div');
        nameDiv.innerHTML = (rid ? rid.iconMd : '') + esc(name) + '<span class="col-path">' + esc(short) + '</span>';
        nameDiv.title = repo;
        nameDiv.style.cursor = 'pointer';
        nameDiv.onclick = function() { loadRepo(repo); };
        header.appendChild(nameDiv);
        col.appendChild(header);

        var list = document.createElement('div');
        list.className = 'home-conv-list';
        list.innerHTML = '<div style="padding:8px 12px;color:#999;font-size:12px">Loading...</div>';
        col.appendChild(list);
        container.appendChild(col);

        fetch('/api/repos/claude-files/?repo=' + encodeURIComponent(repo))
          .then(r => r.json())
          .then(files => {
            list.innerHTML = '';
            if (!files.length) {
              list.innerHTML = '<div style="padding:8px 12px;color:#999;font-size:12px">No CLAUDE.md files</div>';
              return;
            }
            files.forEach(function(f) {
              var item = document.createElement('div');
              item.className = 'home-conv-item';
              item.style.cursor = 'pointer';
              item.style.fontFamily = 'monospace';
              item.style.fontSize = '12px';
              var relDir = f.dir.replace(/^\/home\/[^/]+\//, '~/');
              var sizeStr = f.size < 1024 ? f.size + ' B' : (f.size / 1024).toFixed(1) + ' KB';
              var lines = f.content ? f.content.split('\n').length : 0;
              item.innerHTML = '<div class="conv-meta"><span style="font-size:10px;color:#888">' + esc(sizeStr) + ', ' + lines + ' lines</span></div>' +
                '<div>' + esc(f.name) + '</div>' +
                '<div style="font-size:11px;color:#888;margin-top:1px">' + esc(relDir) + '</div>';
              item.onclick = function() { loadRepo(repo); };
              list.appendChild(item);
            });
          });
      });
    });
}

export function loadRepo(repoPath, pushHistory) {
  setActiveScreen({ activeRepoPath: repoPath });
  if (pushHistory !== false) {
    history.pushState({repoPath: repoPath}, '', '/repos/detail/' + encodeURIComponent(repoPath));
  }
  document.querySelectorAll('.repo-item').forEach(el => {
    el.classList.toggle('active', el.dataset.path === repoPath);
  });
  if (!repoListEl.children.length) loadReposSidebar();
  mainEl.innerHTML = '<div class="empty">Loading...</div>';

  var short = repoPath.replace(/^\/home\/[^/]+\//, '~/');
  var name = short.split('/').pop();
  var rid = RepoIdentity.get(repoPath);

  fetch('/api/repos/claude-files/?repo=' + encodeURIComponent(repoPath))
    .then(r => r.json())
    .then(files => {
      if (files.error) {
        mainEl.innerHTML = '<div class="empty">' + esc(files.error) + '</div>';
        return;
      }

      mainEl.innerHTML = '';

      var toolbar = document.createElement('div');
      toolbar.className = 'conversation-toolbar';
      toolbar.innerHTML = '<span class="header-btns"><span class="close-conv" title="Close">&times;</span></span>';
      toolbar.querySelector('.close-conv').onclick = function() { closeConversation('repos'); };
      mainEl.appendChild(toolbar);

      var header = document.createElement('div');
      header.className = 'conversation-header';
      if (rid) {
        header.style.borderLeft = '3px solid ' + rid.colorBorder;
        header.style.paddingLeft = '12px';
      }
      header.innerHTML =
        '<span>' + (rid ? rid.iconMd : '') + esc(name) + '</span>' +
        '<span style="font-family:monospace;font-size:11px">' + esc(repoPath) + '</span>';
      mainEl.appendChild(header);

      var view = document.createElement('div');
      view.className = 'skill-detail-view';

      if (!files.length) {
        view.innerHTML = '<div style="padding:16px;color:#999">No CLAUDE.md files found</div>';
        mainEl.appendChild(view);
        return;
      }

      var groupLabels = {global: 'Global', parent: 'Parent directories', repo: 'Repository root', subdir: 'Subdirectories'};
      var groupOrder = ['global', 'parent', 'repo', 'subdir'];
      var groups = {};
      files.forEach(function(f) {
        var g = f.group || 'repo';
        if (!groups[g]) groups[g] = [];
        groups[g].push(f);
      });

      var tree = document.createElement('div');
      tree.className = 'claude-file-tree';

      groupOrder.forEach(function(g) {
        if (!groups[g]) return;
        var group = document.createElement('div');
        group.className = 'claude-file-group';
        var lbl = document.createElement('div');
        lbl.className = 'claude-file-group-label';
        lbl.textContent = groupLabels[g];
        group.appendChild(lbl);

        groups[g].forEach(function(f) {
          var details = document.createElement('details');
          details.className = 'claude-file-details';

          var summary = document.createElement('summary');
          summary.className = 'claude-file-item';
          var relDir = f.dir.replace(/^\/home\/[^/]+\//, '~/');
          var sizeStr = f.size < 1024 ? f.size + ' B' : (f.size / 1024).toFixed(1) + ' KB';
          var lines = f.content ? f.content.split('\n').length : 0;
          var modDate = f.modified ? f.modified.substring(0, 10) : '';
          summary.innerHTML = esc(f.name) +
            '<span class="claude-file-meta">' +
              '<span>' + esc(sizeStr) + ', ' + lines + ' lines</span>' +
              '<span>' + esc(modDate) + '</span>' +
              '<span>' + esc(relDir) + '</span>' +
            '</span>';
          summary.title = f.path;
          details.appendChild(summary);

          var body = document.createElement('div');
          body.className = 'claude-file-body';
          var editorBtn = document.createElement('button');
          editorBtn.textContent = '$EDITOR';
          editorBtn.onclick = function(e) { e.stopPropagation(); openInEditor(f.path); };
          body.appendChild(editorBtn);
          var pre = document.createElement('div');
          pre.className = 'claude-file-preview';
          pre.innerHTML = renderMarkdown(f.content || '');
          body.appendChild(pre);
          details.appendChild(body);

          group.appendChild(details);
        });

        tree.appendChild(group);
      });

      var expandBtn = document.createElement('button');
      expandBtn.className = 'claude-file-expand-btn';
      expandBtn.textContent = 'Expand all';
      expandBtn.onclick = function() {
        var allDetails = tree.querySelectorAll('details.claude-file-details');
        var willOpen = expandBtn.textContent === 'Expand all';
        allDetails.forEach(function(d) { d.open = willOpen; });
        expandBtn.textContent = willOpen ? 'Collapse all' : 'Expand all';
      };
      view.appendChild(expandBtn);

      view.appendChild(tree);
      mainEl.appendChild(view);
      renderRichBlocks();
      mainEl.scrollTop = 0;
      mainEl.focus();
    });
}
