import { esc, formatDate } from '/js/utils.js';
import {
  currentForgeRepo,
  currentForgeOrigin,
  currentPR,
  forgeRepoUrl,
  forgeBranchUrl,
  setForgeAutolink,
} from '/js/forge.js';
import { renderMarkdown, renderRichBlocks } from '/js/render.js';

let planListEl, mainEl, setActiveScreen, closeConversation, RepoIdentity;
let getActivePlanId;

export function initPlans(deps) {
  planListEl = deps.planListEl;
  mainEl = deps.mainEl;
  setActiveScreen = deps.setActiveScreen;
  closeConversation = deps.closeConversation;
  RepoIdentity = deps.RepoIdentity;
  getActivePlanId = deps.getActivePlanId;
}

export function loadPlansSidebar() {
  fetch('/api/plans/')
    .then((r) => r.json())
    .then((plansList) => {
      planListEl.innerHTML = '';
      plansList.forEach((p) => {
        var div = document.createElement('div');
        div.className = 'plan-item';
        div.dataset.id = p.id;
        if (p.id === getActivePlanId()) div.classList.add('active');

        var project = p.project
          ? p.project.replace(/^\/home\/[^/]+\//, '~/')
          : '';
        var plrid = p.project ? RepoIdentity.get(p.project) : null;
        div.innerHTML =
          '<div class="plan-info">' +
          (p.date ? '<span>' + esc(formatDate(p.date)) + '</span>' : '') +
          (project
            ? '<span>' + (plrid ? plrid.iconSm : '') + esc(project) + '</span>'
            : '') +
          (p.branch ? '<span>' + esc(p.branch) + '</span>' : '') +
          '</div>' +
          '<div class="plan-title">' +
          esc(p.title) +
          '</div>';

        div.onclick = function () {
          loadPlan(p.id);
        };
        planListEl.appendChild(div);
      });
    });
}

export function showPlansHome() {
  fetch('/api/plans/')
    .then((r) => r.json())
    .then((plansList) => {
      // Group plans by project/cwd
      var repos = {};
      var repoOrder = [];
      var ungrouped = [];
      plansList.forEach((p) => {
        if (p.project) {
          if (!repos[p.project]) {
            repos[p.project] = [];
            repoOrder.push(p.project);
          }
          repos[p.project].push(p);
        } else {
          ungrouped.push(p);
        }
      });

      var container = document.getElementById('home-cols');
      if (!container) return;

      function addPlanColumn(cwd, plans) {
        var short = cwd ? cwd.replace(/^\/home\/[^/]+\//, '~/') : 'Other';
        var name = cwd ? short.split('/').pop() : 'Other';

        var col = document.createElement('div');
        col.className = 'home-column';
        var rid = cwd ? RepoIdentity.get(cwd) : null;

        var header = document.createElement('div');
        header.className = 'home-column-header';
        if (rid) {
          header.style.background = rid.colorLight;
          col.style.borderTop = '3px solid ' + rid.colorBorder;
        }
        var nameDiv = document.createElement('div');
        nameDiv.innerHTML =
          (rid ? rid.iconMd : '') +
          esc(name) +
          (cwd ? '<span class="col-path">' + esc(short) + '</span>' : '');
        if (cwd) nameDiv.title = cwd;
        header.appendChild(nameDiv);
        col.appendChild(header);

        var list = document.createElement('div');
        list.className = 'home-conv-list';

        plans.forEach(function (p) {
          var item = document.createElement('div');
          item.className = 'home-conv-item';
          var meta = '<div class="conv-meta">';
          if (p.date) meta += '<span>' + esc(formatDate(p.date)) + '</span>';
          if (p.branch) meta += '<span>' + esc(p.branch) + '</span>';
          meta += '</div>';
          item.innerHTML = meta + '<div>' + esc(p.title) + '</div>';
          item.onclick = function () {
            loadPlan(p.id);
          };
          list.appendChild(item);
        });

        col.appendChild(list);
        container.appendChild(col);
      }

      repoOrder.forEach(function (cwd) {
        addPlanColumn(cwd, repos[cwd]);
      });
      if (ungrouped.length) {
        addPlanColumn('', ungrouped);
      }
    });
}

export function loadPlan(planId, pushHistory) {
  setActiveScreen({ activePlanId: planId });
  if (pushHistory !== false) {
    history.pushState({ planId: planId }, '', '/plans/' + planId);
  }
  document.querySelectorAll('.plan-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.id === planId);
  });
  if (!planListEl.children.length) loadPlansSidebar();
  mainEl.innerHTML = '<div class="empty">Loading...</div>';

  fetch('/api/plans/' + planId + '/')
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        mainEl.innerHTML = '<div class="empty">' + esc(data.error) + '</div>';
        return;
      }

      var renderPlan = function () {
        mainEl.innerHTML = '';

        var toolbar = document.createElement('div');
        toolbar.className = 'conversation-toolbar';
        toolbar.innerHTML =
          '<span class="header-btns"><span class="close-conv" title="Close">&times;</span></span>';
        toolbar.querySelector('.close-conv').onclick = function () {
          closeConversation('plans');
        };
        mainEl.appendChild(toolbar);

        var header = document.createElement('div');
        header.className = 'conversation-header';
        var prid = data.cwd ? RepoIdentity.get(data.cwd) : null;
        if (prid) {
          header.style.borderLeft = '3px solid ' + prid.colorBorder;
          header.style.paddingLeft = '12px';
        }
        var parts = [];

        var project = data.cwd
          ? data.cwd.replace(/^\/home\/[^/]+\//, '~/')
          : '';
        if (project && currentForgeRepo) {
          parts.push(
            '<span>' +
              (prid ? prid.iconSm : '') +
              '<a href="' +
              esc(forgeRepoUrl(currentForgeRepo)) +
              '" target="_blank" rel="noopener noreferrer">' +
              esc(project) +
              '</a></span>',
          );
        } else if (project) {
          parts.push(
            '<span>' + (prid ? prid.iconSm : '') + esc(project) + '</span>',
          );
        }
        if (data.branch) {
          if (currentForgeOrigin) {
            parts.push(
              '<span>branch: <a href="' +
                esc(forgeBranchUrl(currentForgeOrigin, data.branch)) +
                '" target="_blank" rel="noopener noreferrer">' +
                esc(data.branch) +
                '</a></span>',
            );
          } else {
            parts.push('<span>branch: ' + esc(data.branch) + '</span>');
          }
        }
        if (currentPR) {
          var prLabel =
            currentForgeRepo && currentForgeRepo.type === 'gitlab'
              ? 'MR'
              : 'PR';
          var prPrefix =
            currentForgeRepo && currentForgeRepo.type === 'gitlab' ? '!' : '#';
          parts.push(
            '<span>' +
              prLabel +
              ': <a href="' +
              esc(currentPR.url) +
              '" target="_blank" rel="noopener noreferrer">' +
              prPrefix +
              currentPR.number +
              '</a>' +
              (currentPR.state === 'MERGED'
                ? ' (merged)'
                : currentPR.state === 'CLOSED'
                  ? ' (closed)'
                  : '') +
              '</span>',
          );
        }
        if (data.conversation_id) {
          parts.push(
            '<span>conversation: <a href="/conversations/' +
              esc(data.conversation_id) +
              '" style="color:#4338ca">' +
              esc(data.conversation_id.substring(0, 8)) +
              '...</a></span>',
          );
        }
        header.innerHTML = parts.join('');
        mainEl.appendChild(header);

        var view = document.createElement('div');
        view.className = 'plan-detail-view';

        var actions = document.createElement('div');
        actions.className = 'plan-actions';

        var execBtn = document.createElement('button');
        execBtn.textContent = 'Execute plan';
        execBtn.onclick = function () {
          execBtn.textContent = '...';
          fetch('/api/plans/' + planId + '/execute/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cwd: data.cwd || '' }),
          })
            .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
            .then(function (resp) {
              execBtn.textContent = resp.ok ? 'Launched' : 'Error';
              setTimeout(function () {
                execBtn.textContent = 'Execute plan';
              }, 2000);
            });
        };
        actions.appendChild(execBtn);
        view.appendChild(actions);

        var planBlock = document.createElement('div');
        planBlock.className = 'block plan-block';
        planBlock.innerHTML =
          '<div class="plan-header">' +
          esc(data.title) +
          '</div>' +
          '<div class="plan-content">' +
          renderMarkdown(data.content) +
          '</div>';
        view.appendChild(planBlock);

        mainEl.appendChild(view);
        renderRichBlocks();
        mainEl.scrollTop = 0;
        mainEl.focus();
      };

      if (data.cwd) {
        fetch(
          '/api/github-repo/?path=' +
            encodeURIComponent(data.cwd) +
            '&branch=' +
            encodeURIComponent(data.branch || ''),
        )
          .then((r) => r.json())
          .then((gh) => {
            setForgeAutolink(gh);
            renderPlan();
          })
          .catch(() => {
            setForgeAutolink(null);
            renderPlan();
          });
      } else {
        setForgeAutolink(null);
        renderPlan();
      }
    });
}
