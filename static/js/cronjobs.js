import { esc, timeUntil, formatDate } from '/js/utils.js';
import { renderMarkdown, renderRichBlocks } from '/js/render.js';

let cronjobListEl, mainEl, setActiveScreen, closeConversation, loadConversation;
let getActiveCronjobId;
let RepoIdentity, navigateToSkillByName;

export function initCronjobs(deps) {
  cronjobListEl = deps.cronjobListEl;
  mainEl = deps.mainEl;
  setActiveScreen = deps.setActiveScreen;
  closeConversation = deps.closeConversation;
  loadConversation = deps.loadConversation;
  getActiveCronjobId = deps.getActiveCronjobId;
  RepoIdentity = deps.RepoIdentity;
  navigateToSkillByName = deps.navigateToSkillByName;
}

export function loadCronjobsSidebar() {
  fetch('/api/cronjobs/')
    .then(function (r) {
      return r.json();
    })
    .then(function (cronjobs) {
      cronjobListEl.innerHTML = '';
      cronjobs.forEach(function (cj) {
        var div = document.createElement('div');
        div.className = 'cronjob-item';
        div.dataset.id = cj.id;
        if (cj.id == getActiveCronjobId()) div.classList.add('active');

        var repoShort = cj.repo.replace(/^\/home\/[^/]+\//, '~/');
        var rid = RepoIdentity.get(cj.repo);
        var nextInfo = cj.next_run_at
          ? ' <span style="color:#666">' +
            esc(timeUntil(cj.next_run_at)) +
            '</span>'
          : '';
        div.innerHTML =
          '<div class="cronjob-schedule">' +
          esc(cj.schedule_summary) +
          (cj.enabled
            ? nextInfo
            : ' <span style="color:#dc2626">(off)</span>') +
          '</div>' +
          '<div class="cronjob-name">/' +
          esc(cj.skill_name) +
          '</div>' +
          '<div class="cronjob-repo">' +
          (rid ? rid.iconSm : '') +
          esc(repoShort) +
          '</div>';

        div.onclick = function () {
          loadCronjob(cj.id);
        };
        cronjobListEl.appendChild(div);
      });
    });
}

export function showCronjobsHome() {
  fetch('/api/cronjobs/')
    .then(function (r) {
      return r.json();
    })
    .then(function (cronjobs) {
      var colsEl = document.getElementById('home-cols');
      if (!cronjobs.length) {
        colsEl.innerHTML =
          '<div style="color:#888;padding:24px">No cronjobs yet. Create one from a skill detail view or click + in the sidebar.</div>';
        return;
      }
      var repos = {};
      var repoOrder = [];
      cronjobs.forEach(function (cj) {
        var key = cj.repo || 'other';
        if (!repos[key]) {
          repos[key] = [];
          repoOrder.push(key);
        }
        repos[key].push(cj);
      });
      colsEl.innerHTML = '';
      repoOrder.forEach(function (repo) {
        var col = document.createElement('div');
        col.className = 'home-column';
        var rid = RepoIdentity.get(repo);
        var short = repo.replace(/^\/home\/[^/]+\//, '~/');
        if (rid) {
          col.style.borderColor = rid.colorBorder;
          col.style.background = rid.colorLight;
        }
        col.innerHTML =
          '<div class="home-column-header">' +
          (rid ? rid.iconMd : '') +
          '<strong>' +
          esc(short) +
          '</strong></div>';
        repos[repo].forEach(function (cj) {
          var item = document.createElement('div');
          item.className = 'home-conv-item';
          item.innerHTML =
            '<div style="font-size:11px;color:#888">' +
            esc(cj.schedule_summary) +
            (cj.enabled ? '' : ' <span style="color:#dc2626">(off)</span>') +
            '</div>' +
            '<div>/' +
            esc(cj.skill_name) +
            '</div>';
          item.onclick = function () {
            loadCronjob(cj.id);
          };
          col.appendChild(item);
        });
        colsEl.appendChild(col);
      });
    });
}

export function loadCronjob(cronjobId, pushHistory) {
  setActiveScreen({ activeCronjobId: cronjobId });
  if (pushHistory !== false) {
    history.pushState(null, '', '/cronjobs/' + cronjobId);
  }
  document.querySelectorAll('.cronjob-item').forEach(function (el) {
    el.classList.toggle('active', el.dataset.id == cronjobId);
  });
  if (!cronjobListEl.children.length) loadCronjobsSidebar();

  mainEl.innerHTML = '<div class="empty">Loading...</div>';
  fetch('/api/cronjobs/' + cronjobId + '/')
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      if (getActiveCronjobId() !== cronjobId) return;
      mainEl.innerHTML = '';

      var toolbar = document.createElement('div');
      toolbar.className = 'conversation-toolbar';
      var closeBtn = document.createElement('button');
      closeBtn.className = 'close-conv';
      closeBtn.innerHTML = '&#x2715;';
      closeBtn.title = 'Close';
      closeBtn.onclick = function () {
        closeConversation('cronjobs');
      };
      toolbar.appendChild(closeBtn);
      mainEl.appendChild(toolbar);

      var header = document.createElement('div');
      header.className = 'conversation-header';
      var repoShort = data.repo.replace(/^\/home\/[^/]+\//, '~/');
      var nextRunInfo = data.next_run_at
        ? ' (next: ' + timeUntil(data.next_run_at) + ')'
        : '';
      header.innerHTML =
        '<span style="font-size:18px;font-weight:700">/' +
        esc(data.skill_name) +
        '</span>' +
        '<span style="font-size:13px;color:#888">' +
        esc(data.schedule_summary) +
        nextRunInfo +
        '</span>' +
        '<span style="font-size:13px;color:#888">' +
        esc(repoShort) +
        '</span>';
      mainEl.appendChild(header);

      var view = document.createElement('div');
      view.className = 'cronjob-detail-view';

      var form = document.createElement('div');
      form.className = 'cronjob-form';

      // Skill dropdown
      var skillLabel = document.createElement('label');
      skillLabel.textContent = 'Skill';
      var skillSelect = document.createElement('select');
      skillSelect.innerHTML = '<option value="">Loading...</option>';
      fetch('/api/skills/')
        .then(function (r) {
          return r.json();
        })
        .then(function (skills) {
          skillSelect.innerHTML = '';
          skills.forEach(function (s) {
            var opt = document.createElement('option');
            opt.value = s.name;
            opt.textContent =
              '/' +
              s.name +
              ' (' +
              (s.scope === 'global'
                ? 'global'
                : s.scope.replace(/^\/home\/[^/]+\//, '~/')) +
              ')';
            if (s.name === data.skill_name) opt.selected = true;
            skillSelect.appendChild(opt);
          });
        });
      skillLabel.appendChild(skillSelect);

      var skillLink = document.createElement('a');
      skillLink.href = '#';
      skillLink.textContent = 'View skill';
      skillLink.style.cssText =
        'font-size:11px;color:#4338ca;font-weight:normal';
      skillLink.onclick = function (e) {
        e.preventDefault();
        navigateToSkillByName(data.skill_name);
      };
      skillLabel.appendChild(skillLink);
      form.appendChild(skillLabel);

      // Repo dropdown
      var repoLabel = document.createElement('label');
      repoLabel.textContent = 'Repository';
      var repoSelect = document.createElement('select');
      repoSelect.innerHTML = '<option value="">Loading...</option>';
      fetch('/api/repos/')
        .then(function (r) {
          return r.json();
        })
        .then(function (repos) {
          repoSelect.innerHTML = '';
          repos.forEach(function (repo) {
            var opt = document.createElement('option');
            opt.value = repo;
            opt.textContent = repo.replace(/^\/home\/[^/]+\//, '~/');
            if (repo === data.repo) opt.selected = true;
            repoSelect.appendChild(opt);
          });
          if (!repos.includes(data.repo)) {
            var opt = document.createElement('option');
            opt.value = data.repo;
            opt.textContent = data.repo.replace(/^\/home\/[^/]+\//, '~/');
            opt.selected = true;
            repoSelect.prepend(opt);
          }
        });
      repoLabel.appendChild(repoSelect);
      form.appendChild(repoLabel);

      // Params
      var paramsLabel = document.createElement('label');
      paramsLabel.textContent = 'Params';
      var paramsInput = document.createElement('input');
      paramsInput.type = 'text';
      paramsInput.value = data.params;
      paramsInput.placeholder = 'optional arguments';
      paramsLabel.appendChild(paramsInput);
      form.appendChild(paramsLabel);

      // Schedule
      var schedLabel = document.createElement('label');
      schedLabel.textContent = 'Schedule (cron expression)';
      var cronInput = document.createElement('input');
      cronInput.type = 'text';
      cronInput.value = data.cron_expression;
      cronInput.placeholder = '0 18 * * *';
      schedLabel.appendChild(cronInput);

      var presets = document.createElement('div');
      presets.className = 'schedule-presets';
      var presetDefs = [
        { label: 'Daily 9am', value: '0 9 * * *' },
        { label: 'Daily 6pm', value: '0 18 * * *' },
        { label: 'Weekdays 9am', value: '0 9 * * 1-5' },
        { label: 'Mon 9am', value: '0 9 * * 1' },
        { label: 'Every hour', value: '0 * * * *' },
      ];
      presetDefs.forEach(function (p) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = p.label;
        btn.onclick = function () {
          cronInput.value = p.value;
        };
        presets.appendChild(btn);
      });
      schedLabel.appendChild(presets);
      form.appendChild(schedLabel);

      // Enabled
      var enabledLabel = document.createElement('label');
      enabledLabel.style.flexDirection = 'row';
      enabledLabel.style.alignItems = 'center';
      enabledLabel.style.gap = '8px';
      var enabledCheck = document.createElement('input');
      enabledCheck.type = 'checkbox';
      enabledCheck.checked = data.enabled;
      enabledLabel.appendChild(enabledCheck);
      enabledLabel.appendChild(document.createTextNode('Enabled'));
      form.appendChild(enabledLabel);

      view.appendChild(form);

      // Actions
      var actions = document.createElement('div');
      actions.className = 'cronjob-actions';
      actions.style.marginTop = '16px';

      var saveBtn = document.createElement('button');
      saveBtn.textContent = 'Save';
      saveBtn.onclick = function () {
        saveBtn.textContent = '...';
        fetch('/api/cronjobs/' + cronjobId + '/', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            skill_name: skillSelect.value || data.skill_name,
            repo: repoSelect.value || data.repo,
            params: paramsInput.value,
            cron_expression: cronInput.value,
            enabled: enabledCheck.checked,
          }),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { ok: r.ok, data: d };
            });
          })
          .then(function (resp) {
            if (resp.ok) {
              saveBtn.textContent = 'Saved';
              loadCronjobsSidebar();
              setTimeout(function () {
                saveBtn.textContent = 'Save';
              }, 2000);
            } else {
              saveBtn.textContent = resp.data.error || 'Error';
              setTimeout(function () {
                saveBtn.textContent = 'Save';
              }, 2000);
            }
          });
      };
      actions.appendChild(saveBtn);

      var runNowBtn = document.createElement('button');
      runNowBtn.textContent = 'Run Now';
      runNowBtn.onclick = function () {
        runNowBtn.textContent = '...';
        fetch('/api/cronjobs/' + cronjobId + '/run/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { ok: r.ok, data: d };
            });
          })
          .then(function (resp) {
            runNowBtn.textContent = resp.ok ? 'Launched' : 'Error';
            setTimeout(function () {
              runNowBtn.textContent = 'Run Now';
            }, 2000);
          });
      };
      actions.appendChild(runNowBtn);

      var deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.style.cssText = 'color:#dc2626;border-color:#fca5a5';
      deleteBtn.onclick = function () {
        if (!confirm('Delete this cronjob?')) return;
        fetch('/api/cronjobs/' + cronjobId + '/', { method: 'DELETE' }).then(
          function () {
            loadCronjobsSidebar();
            closeConversation('cronjobs');
          },
        );
      };
      actions.appendChild(deleteBtn);

      view.appendChild(actions);

      // Previous runs
      var runsSection = document.createElement('div');
      runsSection.className = 'cronjob-runs';
      runsSection.innerHTML = '<h4>Previous runs</h4>';

      if (!data.runs || !data.runs.length) {
        runsSection.innerHTML +=
          '<div style="color:#888;font-size:13px">No runs yet</div>';
      } else {
        data.runs.forEach(function (run) {
          var item = document.createElement('div');
          item.className = 'cronjob-run-item';
          var badgeClass =
            run.trigger_type === 'manual' ? 'badge-manual' : 'badge-scheduled';
          var convLink = run.conversation_id
            ? '<a href="/conversations/' +
              esc(run.conversation_id) +
              '" style="color:#4338ca;font-size:12px">' +
              esc(run.conversation_id.substring(0, 8)) +
              '...</a>'
            : '<span style="color:#aaa;font-size:12px">no conversation linked</span>';
          item.innerHTML =
            '<span>' +
            esc(formatDate(run.triggered_at)) +
            '</span>' +
            '<span class="badge ' +
            badgeClass +
            '">' +
            esc(run.trigger_type) +
            '</span>' +
            '<span>' +
            convLink +
            '</span>';
          if (run.conversation_id) {
            item.style.cursor = 'pointer';
            item.onclick = function (e) {
              if (e.target.tagName === 'A') {
                e.preventDefault();
              }
              loadConversation(run.conversation_id);
            };
          }
          runsSection.appendChild(item);
        });
      }
      view.appendChild(runsSection);

      mainEl.appendChild(view);
      mainEl.scrollTop = 0;
      mainEl.focus();
    });
}

export function showCreateCronjobForm(prefilledName, pushHistory) {
  setActiveScreen({ activeNewScreen: 'cronjob' });
  if (pushHistory !== false) {
    history.pushState(null, '', '/cronjobs/new');
  }

  mainEl.innerHTML = '';

  var toolbar = document.createElement('div');
  toolbar.className = 'conversation-toolbar';
  var closeBtn = document.createElement('button');
  closeBtn.className = 'close-conv';
  closeBtn.innerHTML = '&#x2715;';
  closeBtn.title = 'Close';
  closeBtn.onclick = function () {
    closeConversation('cronjobs');
  };
  toolbar.appendChild(closeBtn);
  mainEl.appendChild(toolbar);

  var header = document.createElement('div');
  header.className = 'conversation-header';
  header.innerHTML =
    '<span style="font-size:18px;font-weight:700">New Cronjob</span>';
  mainEl.appendChild(header);

  var view = document.createElement('div');
  view.className = 'cronjob-detail-view';
  var form = document.createElement('div');
  form.className = 'cronjob-form';

  // Skill dropdown
  var skillLabel = document.createElement('label');
  skillLabel.textContent = 'Skill';
  var skillSelect = document.createElement('select');
  skillSelect.innerHTML = '<option value="">Loading...</option>';
  fetch('/api/skills/')
    .then(function (r) {
      return r.json();
    })
    .then(function (skills) {
      skillSelect.innerHTML = '';
      skills.forEach(function (s) {
        var opt = document.createElement('option');
        opt.value = s.name;
        opt.textContent =
          '/' +
          s.name +
          ' (' +
          (s.scope === 'global'
            ? 'global'
            : s.scope.replace(/^\/home\/[^/]+\//, '~/')) +
          ')';
        if (prefilledName && s.name === prefilledName) opt.selected = true;
        skillSelect.appendChild(opt);
      });
    });
  skillLabel.appendChild(skillSelect);
  form.appendChild(skillLabel);

  // Repo dropdown
  var repoLabel = document.createElement('label');
  repoLabel.textContent = 'Repository';
  var repoSelect = document.createElement('select');
  repoSelect.innerHTML = '<option value="">Loading...</option>';
  fetch('/api/repos/')
    .then(function (r) {
      return r.json();
    })
    .then(function (repos) {
      repoSelect.innerHTML = '';
      repos.forEach(function (repo) {
        var opt = document.createElement('option');
        opt.value = repo;
        opt.textContent = repo.replace(/^\/home\/[^/]+\//, '~/');
        repoSelect.appendChild(opt);
      });
    });
  repoLabel.appendChild(repoSelect);
  form.appendChild(repoLabel);

  // Params
  var paramsLabel = document.createElement('label');
  paramsLabel.textContent = 'Params';
  var paramsInput = document.createElement('input');
  paramsInput.type = 'text';
  paramsInput.placeholder = 'optional arguments';
  paramsLabel.appendChild(paramsInput);
  form.appendChild(paramsLabel);

  // Schedule
  var schedLabel = document.createElement('label');
  schedLabel.textContent = 'Schedule (cron expression)';
  var cronInput = document.createElement('input');
  cronInput.type = 'text';
  cronInput.value = '0 9 * * *';
  cronInput.placeholder = '0 18 * * *';
  schedLabel.appendChild(cronInput);

  var presets = document.createElement('div');
  presets.className = 'schedule-presets';
  var presetDefs = [
    { label: 'Daily 9am', value: '0 9 * * *' },
    { label: 'Daily 6pm', value: '0 18 * * *' },
    { label: 'Weekdays 9am', value: '0 9 * * 1-5' },
    { label: 'Mon 9am', value: '0 9 * * 1' },
    { label: 'Every hour', value: '0 * * * *' },
  ];
  presetDefs.forEach(function (p) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = p.label;
    btn.onclick = function () {
      cronInput.value = p.value;
    };
    presets.appendChild(btn);
  });
  schedLabel.appendChild(presets);
  form.appendChild(schedLabel);

  view.appendChild(form);

  // Actions
  var actions = document.createElement('div');
  actions.className = 'cronjob-actions';
  actions.style.marginTop = '16px';

  var statusSpan = document.createElement('span');
  statusSpan.style.cssText = 'font-size:13px;color:#888;align-self:center';

  var createBtn = document.createElement('button');
  createBtn.textContent = 'Create';
  createBtn.onclick = function () {
    if (!skillSelect.value || !repoSelect.value || !cronInput.value) {
      statusSpan.textContent = 'Fill in all required fields';
      setTimeout(function () {
        statusSpan.textContent = '';
      }, 2000);
      return;
    }
    createBtn.textContent = '...';
    fetch('/api/cronjobs/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        skill_name: skillSelect.value,
        repo: repoSelect.value,
        params: paramsInput.value,
        cron_expression: cronInput.value,
      }),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, data: d };
        });
      })
      .then(function (resp) {
        if (resp.ok) {
          loadCronjobsSidebar();
          loadCronjob(resp.data.id);
        } else {
          createBtn.textContent = 'Create';
          statusSpan.textContent = resp.data.error || 'Error';
          setTimeout(function () {
            statusSpan.textContent = '';
          }, 2000);
        }
      });
  };
  actions.appendChild(createBtn);

  var cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.onclick = function () {
    closeConversation('cronjobs');
  };
  actions.appendChild(cancelBtn);

  actions.appendChild(statusSpan);
  view.appendChild(actions);

  mainEl.appendChild(view);
  mainEl.scrollTop = 0;
  mainEl.focus();
}
