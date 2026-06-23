import { esc, openInEditor } from '/js/utils.js';
import { renderMarkdown, renderRichBlocks } from '/js/render.js';
import { forgeBranchUrl, forgePrUrl, forgeRepoUrl } from '/js/forge.js';

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
    .then((r) => r.json())
    .then((repos) => {
      repoListEl.innerHTML = '';
      repos.forEach((entry) => {
        var repo = entry.path || entry;
        var exists = entry.exists !== false;
        var div = document.createElement('div');
        div.className = 'repo-item';
        if (!exists) div.classList.add('repo-stale');
        div.dataset.path = repo;
        if (repo === getActiveRepoPath()) div.classList.add('active');

        var short = repo.replace(/^\/home\/[^/]+\//, '~/');
        var name = short.split('/').pop();
        var rid = RepoIdentity.get(repo);
        div.innerHTML =
          '<div class="repo-name">' +
          (rid ? rid.iconSm : '') +
          esc(name) +
          '</div>' +
          '<div class="repo-path">' +
          esc(short) +
          '</div>';

        div.onclick = function () {
          loadRepo(repo);
        };
        repoListEl.appendChild(div);
      });
    });
}

export function showReposHome() {
  fetch('/api/repos/')
    .then((r) => r.json())
    .then((repos) => {
      var container = document.getElementById('home-cols');
      if (!container) return;

      repos.forEach(function (entry) {
        var repo = entry.path || entry;
        var exists = entry.exists !== false;
        if (!exists) return;
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
        nameDiv.innerHTML =
          (rid ? rid.iconMd : '') +
          esc(name) +
          '<span class="col-path">' +
          esc(short) +
          '</span>';
        nameDiv.title = repo;
        nameDiv.style.cursor = 'pointer';
        nameDiv.onclick = function () {
          loadRepo(repo);
        };
        header.appendChild(nameDiv);
        col.appendChild(header);

        var list = document.createElement('div');
        list.className = 'home-conv-list';
        list.innerHTML =
          '<div style="padding:8px 12px;color:#999;font-size:12px">Loading...</div>';
        col.appendChild(list);
        container.appendChild(col);

        fetch('/api/repos/claude-files/?repo=' + encodeURIComponent(repo))
          .then((r) => r.json())
          .then((files) => {
            list.innerHTML = '';
            if (!files.length) {
              list.innerHTML =
                '<div style="padding:8px 12px;color:#999;font-size:12px">No CLAUDE.md files</div>';
              return;
            }
            files.forEach(function (f) {
              var item = document.createElement('div');
              item.className = 'home-conv-item';
              item.style.cursor = 'pointer';
              item.style.fontFamily = 'monospace';
              item.style.fontSize = '12px';
              var relDir = f.dir.replace(/^\/home\/[^/]+\//, '~/');
              var sizeStr =
                f.size < 1024
                  ? f.size + ' B'
                  : (f.size / 1024).toFixed(1) + ' KB';
              var lines = f.content ? f.content.split('\n').length : 0;
              item.innerHTML =
                '<div class="conv-meta"><span style="font-size:10px;color:#888">' +
                esc(sizeStr) +
                ', ' +
                lines +
                ' lines</span></div>' +
                '<div>' +
                esc(f.name) +
                '</div>' +
                '<div style="font-size:11px;color:#888;margin-top:1px">' +
                esc(relDir) +
                '</div>';
              item.onclick = function () {
                loadRepo(repo);
              };
              list.appendChild(item);
            });
          });
      });
    });
}

export function loadRepo(repoPath, pushHistory) {
  setActiveScreen({ activeRepoPath: repoPath });
  if (pushHistory !== false) {
    history.pushState(
      { repoPath: repoPath },
      '',
      '/repos/detail/' + encodeURIComponent(repoPath),
    );
  }
  document.querySelectorAll('.repo-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.path === repoPath);
  });
  if (!repoListEl.children.length) loadReposSidebar();
  mainEl.innerHTML = '<div class="empty">Loading...</div>';

  var short = repoPath.replace(/^\/home\/[^/]+\//, '~/');
  var name = short.split('/').pop();
  var rid = RepoIdentity.get(repoPath);

  Promise.all([
    fetch('/api/repos/claude-files/?repo=' + encodeURIComponent(repoPath)).then(
      (r) => r.json(),
    ),
    fetch('/api/repos/git-info/?repo=' + encodeURIComponent(repoPath))
      .then((r) => r.json())
      .then((d) => (d.error ? null : d))
      .catch(() => null),
  ]).then(([files, gitInfo]) => {
    if (files.error) {
      mainEl.innerHTML = '<div class="empty">' + esc(files.error) + '</div>';
      return;
    }

    mainEl.innerHTML = '';

    var toolbar = document.createElement('div');
    toolbar.className = 'conversation-toolbar';
    toolbar.innerHTML =
      '<span class="header-btns">' +
      '<span class="toolbar-btn reload-btn" title="Refresh">&#x21bb;</span>' +
      '<span class="close-conv" title="Close">&times;</span>' +
      '</span>';
    toolbar.querySelector('.close-conv').onclick = function () {
      closeConversation('repos');
    };
    toolbar.querySelector('.reload-btn').onclick = function () {
      loadRepo(repoPath, false);
    };
    mainEl.appendChild(toolbar);

    var header = document.createElement('div');
    header.className = 'conversation-header';
    if (rid) {
      header.style.borderLeft = '3px solid ' + rid.colorBorder;
      header.style.paddingLeft = '12px';
    }
    header.innerHTML =
      '<span>' +
      (rid ? rid.iconMd : '') +
      esc(name) +
      '</span>' +
      '<span style="font-family:monospace;font-size:11px">' +
      esc(repoPath) +
      '</span>';
    mainEl.appendChild(header);

    if (gitInfo) {
      mainEl.appendChild(renderGitInfo(gitInfo, repoPath));
    }

    renderClaudeFiles(files, repoPath);

    renderRichBlocks();
    mainEl.scrollTop = 0;
    mainEl.focus();
  });
}

function forgeForTracking(gi, tracking) {
  if (!gi.forge) return null;
  if (tracking && tracking.startsWith('origin/') && gi.forge.origin)
    return gi.forge.origin;
  if (tracking && tracking.startsWith('upstream/') && gi.forge.upstream)
    return gi.forge.upstream;
  return gi.forge.upstream || gi.forge.origin;
}

function renderGitInfo(gi, repoPath) {
  var container = document.createElement('div');
  container.className = 'git-info-container';

  // HEAD status
  if (gi.head) {
    var headSection = document.createElement('div');
    headSection.className = 'git-info-section git-head-bar';

    var headForge = forgeForTracking(gi, gi.head.tracking);
    var branchText = gi.head.branch || '(unknown)';
    var branchHtml;
    if (headForge && branchText !== 'HEAD' && branchText !== '(unknown)') {
      branchHtml =
        '<a href="' +
        esc(forgeBranchUrl(headForge, branchText)) +
        '" target="_blank" rel="noopener noreferrer">' +
        esc(branchText) +
        '</a>';
    } else {
      branchHtml = esc(branchText);
    }

    var dirtyHtml = renderDirtyBadge(gi.head.dirty_count, gi.head.dirty_files);

    var remoteHtml = '';
    if (gi.head.tracking) {
      var statusText = gi.head.remote_status || '';
      var statusClass =
        statusText === 'up to date' ? 'git-remote-ok' : 'git-remote-warn';
      remoteHtml =
        '<span class="git-remote-status ' +
        statusClass +
        '">' +
        esc(gi.head.tracking) +
        (statusText ? ' (' + esc(statusText) + ')' : '') +
        '</span>';
    } else if (gi.head.branch !== 'HEAD' && !gi.head.is_default) {
      remoteHtml =
        '<span class="git-remote-status git-remote-warn">not pushed</span>';
    }

    headSection.innerHTML =
      '<span class="git-head-branch">' +
      branchHtml +
      '</span>' +
      dirtyHtml +
      remoteHtml;

    container.appendChild(headSection);
  }

  // Worktrees
  if (gi.worktrees && gi.worktrees.length > 0) {
    var wtSection = document.createElement('details');
    wtSection.className = 'git-info-section';
    wtSection.open = true;

    var wtSummary = document.createElement('summary');
    wtSummary.className = 'git-section-header';
    wtSummary.textContent = 'Worktrees (' + gi.worktrees.length + ')';
    wtSection.appendChild(wtSummary);

    var wtList = document.createElement('div');
    wtList.className = 'git-worktree-list';

    gi.worktrees.forEach(function (wt) {
      var item = document.createElement('div');
      item.className = 'git-worktree-item';

      var shortPath = wt.path.replace(/^\/home\/[^/]+\//, '~/');
      var dirtyBadge = renderDirtyBadge(wt.dirty_count, wt.dirty_files);

      var sourceLabel =
        wt.source === 'claude'
          ? '<span class="git-wt-source">claude</span>'
          : '';

      var actionsHtml =
        '<span class="git-wt-actions">' +
        '<button class="git-wt-term-btn" title="Open terminal here">$</button>' +
        '</span>';

      item.innerHTML =
        '<span class="git-wt-branch">' +
        esc(wt.branch || '?') +
        '</span>' +
        dirtyBadge +
        sourceLabel +
        '<span class="git-wt-path">' +
        esc(shortPath) +
        '</span>' +
        actionsHtml;

      item.querySelector('.git-wt-term-btn').onclick = function (e) {
        e.stopPropagation();
        fetch('/api/terminal/run/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cmd: ['bash'], cwd: wt.path }),
        });
      };

      wtList.appendChild(item);
    });

    wtSection.appendChild(wtList);
    container.appendChild(wtSection);
  }

  // Branches
  if (gi.branches && gi.branches.length > 0) {
    var brSection = document.createElement('details');
    brSection.className = 'git-info-section';
    brSection.open = true;

    var brSummary = document.createElement('summary');
    brSummary.className = 'git-section-header';

    var brSummaryText = 'Branches (' + gi.branches.length + ')';
    brSummary.textContent = brSummaryText;

    var checkPrsBtn = document.createElement('button');
    checkPrsBtn.className = 'git-check-prs-btn';
    checkPrsBtn.textContent = 'Check PRs';
    checkPrsBtn.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      checkBranchPRs(gi, repoPath, brSection, checkPrsBtn);
    };
    brSummary.appendChild(checkPrsBtn);
    brSection.appendChild(brSummary);

    var brList = document.createElement('div');
    brList.className = 'git-branch-list';

    gi.branches.forEach(function (b) {
      var row = document.createElement('div');
      row.className = 'git-branch-row';
      row.dataset.branch = b.name;

      var headMarker = b.is_head ? '* ' : '  ';

      var brForge = forgeForTracking(gi, b.tracking);
      var nameHtml;
      if (brForge && !b.is_default) {
        nameHtml =
          '<a href="' +
          esc(forgeBranchUrl(brForge, b.name)) +
          '" target="_blank" rel="noopener noreferrer">' +
          esc(b.name) +
          '</a>';
      } else if (brForge && b.is_default) {
        nameHtml =
          '<a href="' +
          esc(forgeRepoUrl(brForge)) +
          '" target="_blank" rel="noopener noreferrer">' +
          esc(b.name) +
          '</a>';
      } else {
        nameHtml = esc(b.name);
      }

      var trackingHtml = '';
      if (b.tracking) {
        trackingHtml = esc(b.tracking);
        if (b.track_status) {
          trackingHtml += ' ' + esc(b.track_status);
        }
      } else if (!b.is_default) {
        trackingHtml = '<span class="git-not-pushed">not pushed</span>';
      }

      var prHtml = renderPrBadge(b.pr, brForge);

      var issuesHtml = '';
      if (b.issues && b.issues.length > 0) {
        issuesHtml = b.issues
          .map(function (iss) {
            return (
              '<a href="' +
              esc(iss.url) +
              '" target="_blank" rel="noopener noreferrer" class="git-issue-link">' +
              esc(iss.key) +
              '</a>'
            );
          })
          .join(' ');
      }

      var dateStr = '';
      if (b.last_commit_date) {
        var d = new Date(b.last_commit_date);
        if (!isNaN(d)) {
          var months = [
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
          dateStr = months[d.getMonth()] + ' ' + d.getDate();
        }
      }

      row.innerHTML =
        '<span class="git-branch-head">' +
        esc(headMarker) +
        '</span>' +
        '<span class="git-branch-name">' +
        nameHtml +
        '</span>' +
        '<span class="git-branch-tracking">' +
        trackingHtml +
        '</span>' +
        '<span class="git-branch-pr">' +
        prHtml +
        '</span>' +
        '<span class="git-branch-issues">' +
        issuesHtml +
        '</span>' +
        '<span class="git-branch-date">' +
        esc(dateStr) +
        '</span>';

      brList.appendChild(row);
    });

    brSection.appendChild(brList);
    container.appendChild(brSection);
  }

  return container;
}

function renderDirtyBadge(count, files) {
  if (count === 0) {
    return '<span class="git-status-badge clean">clean</span>';
  }
  if (count < 0) {
    return '<span class="git-status-badge">?</span>';
  }
  if (!files || !files.length) {
    return '<span class="git-status-badge dirty">' + count + ' dirty</span>';
  }
  return (
    '<details class="git-dirty-details">' +
    '<summary class="git-status-badge dirty">' +
    count +
    ' dirty</summary>' +
    '<div class="git-dirty-files">' +
    files
      .map(function (f) {
        return '<div>' + esc(f) + '</div>';
      })
      .join('') +
    '</div></details>'
  );
}

function renderPrBadge(pr, forge) {
  if (!pr || !pr.number) return '';

  var prPrefix = forge && forge.type === 'gitlab' ? '!' : '#';
  var stateClass = '';
  var stateSuffix = '';
  if (pr.state === 'MERGED' || pr.state === 'merged') {
    stateClass = ' merged';
    stateSuffix = ' merged';
  } else if (pr.state === 'CLOSED' || pr.state === 'closed') {
    stateClass = ' closed';
    stateSuffix = ' closed';
  } else if (pr.state === null) {
    stateClass = ' unknown';
  } else {
    stateClass = ' open';
  }

  return (
    '<a href="' +
    esc(pr.url) +
    '" target="_blank" rel="noopener noreferrer" class="git-pr-badge' +
    stateClass +
    '">' +
    prPrefix +
    pr.number +
    stateSuffix +
    '</a>'
  );
}

function checkBranchPRs(gi, repoPath, brSection, btn) {
  var candidates = gi.branches.filter(function (b) {
    return (
      !b.is_default && ((!b.pr && b.tracking) || (b.pr && b.pr.state === null))
    );
  });

  if (candidates.length === 0) {
    btn.textContent = 'No candidates';
    setTimeout(function () {
      btn.textContent = 'Check PRs';
    }, 2000);
    return;
  }

  btn.disabled = true;
  var done = 0;

  function next() {
    if (done >= candidates.length) {
      btn.textContent = 'Done';
      btn.disabled = false;
      setTimeout(function () {
        btn.textContent = 'Check PRs';
      }, 2000);
      return;
    }

    var b = candidates[done];
    btn.textContent = 'Checking ' + (done + 1) + '/' + candidates.length;

    var url =
      '/api/repos/branch-pr/?repo=' +
      encodeURIComponent(repoPath) +
      '&branch=' +
      encodeURIComponent(b.name);

    if (b.pr && b.pr.number && b.pr.state === null) {
      url += '&pr_number=' + encodeURIComponent(b.pr.number);
    }

    fetch(url)
      .then((r) => r.json())
      .then(function (data) {
        if (data.pr) {
          b.pr = data.pr;
          var row = brSection.querySelector(
            '.git-branch-row[data-branch="' + CSS.escape(b.name) + '"]',
          );
          if (row) {
            var prCell = row.querySelector('.git-branch-pr');
            var forge = gi.forge && (gi.forge.upstream || gi.forge.origin);
            if (prCell) prCell.innerHTML = renderPrBadge(data.pr, forge);
          }
        }
        done++;
        next();
      })
      .catch(function () {
        done++;
        next();
      });
  }

  next();
}

function renderClaudeFiles(files, repoPath) {
  var view = document.createElement('div');
  view.className = 'skill-detail-view';

  if (!files.length) {
    view.innerHTML =
      '<div style="padding:16px;color:#999">No CLAUDE.md files found</div>';
    mainEl.appendChild(view);
    return;
  }

  var groupLabels = {
    global: 'Global',
    parent: 'Parent directories',
    repo: 'Repository root',
    subdir: 'Subdirectories',
  };
  var groupOrder = ['global', 'parent', 'repo', 'subdir'];
  var groups = {};
  files.forEach(function (f) {
    var g = f.group || 'repo';
    if (!groups[g]) groups[g] = [];
    groups[g].push(f);
  });

  var tree = document.createElement('div');
  tree.className = 'claude-file-tree';

  groupOrder.forEach(function (g) {
    if (!groups[g]) return;
    var group = document.createElement('div');
    group.className = 'claude-file-group';
    var lbl = document.createElement('div');
    lbl.className = 'claude-file-group-label';
    lbl.textContent = groupLabels[g];
    group.appendChild(lbl);

    groups[g].forEach(function (f) {
      var details = document.createElement('details');
      details.className = 'claude-file-details';

      var summary = document.createElement('summary');
      summary.className = 'claude-file-item';
      var relDir = f.dir.replace(/^\/home\/[^/]+\//, '~/');
      var sizeStr =
        f.size < 1024 ? f.size + ' B' : (f.size / 1024).toFixed(1) + ' KB';
      var lines = f.content ? f.content.split('\n').length : 0;
      var modDate = f.modified ? f.modified.substring(0, 10) : '';
      summary.innerHTML =
        esc(f.name) +
        '<span class="claude-file-meta">' +
        '<span>' +
        esc(sizeStr) +
        ', ' +
        lines +
        ' lines</span>' +
        '<span>' +
        esc(modDate) +
        '</span>' +
        '<span>' +
        esc(relDir) +
        '</span>' +
        '</span>';
      summary.title = f.path;
      details.appendChild(summary);

      var body = document.createElement('div');
      body.className = 'claude-file-body';
      var editorBtn = document.createElement('button');
      editorBtn.textContent = '$EDITOR';
      editorBtn.onclick = function (e) {
        e.stopPropagation();
        openInEditor(f.path);
      };
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
  expandBtn.onclick = function () {
    var allDetails = tree.querySelectorAll('details.claude-file-details');
    var willOpen = expandBtn.textContent === 'Expand all';
    allDetails.forEach(function (d) {
      d.open = willOpen;
    });
    expandBtn.textContent = willOpen ? 'Collapse all' : 'Expand all';
  };
  view.appendChild(expandBtn);

  view.appendChild(tree);
  mainEl.appendChild(view);
}
