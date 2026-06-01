import { esc, formatDate, openInEditor, timeAgo } from '/js/utils.js';
import { currentCwd } from '/js/forge.js';
import { renderMarkdown, renderRichBlocks } from '/js/render.js';

function kindBadge(kind) {
  if (kind === 'skill') return '<span class="skill-kind-badge kind-skill">skill</span>';
  if (kind === 'workflow') return '<span class="skill-kind-badge kind-workflow">workflow</span>';
  return '<span class="skill-kind-badge">cmd</span>';
}

let skillListEl, mainEl, setActiveScreen, closeConversation, RepoIdentity, loadConversation;
let getActiveSkillId;
let showCreateCronjobForm, loadCronjob;

export function initSkills(deps) {
  skillListEl = deps.skillListEl;
  mainEl = deps.mainEl;
  setActiveScreen = deps.setActiveScreen;
  closeConversation = deps.closeConversation;
  RepoIdentity = deps.RepoIdentity;
  loadConversation = deps.loadConversation;
  getActiveSkillId = deps.getActiveSkillId;
  showCreateCronjobForm = deps.showCreateCronjobForm;
  loadCronjob = deps.loadCronjob;

  document.addEventListener('click', function(e) {
    if (!e.target.closest('.run-dropdown')) {
      document.querySelectorAll('.run-dropdown-panel.open').forEach(function(p) {
        p.classList.remove('open');
      });
    }
  });
}

export function loadSkillsSidebar() {
  fetch('/api/skills/')
    .then(r => r.json())
    .then(skillsList => {
      skillListEl.innerHTML = '';
      skillsList.forEach(s => {
        var div = document.createElement('div');
        div.className = 'skill-item';
        div.dataset.id = s.id;
        if (s.id === getActiveSkillId()) div.classList.add('active');

        var scopeLabel = s.scope === 'global' ? 'global' : s.scope.replace(/^\/home\/[^/]+\//, '~/');
        var skrid = s.scope !== 'global' ? RepoIdentity.get(s.scope) : null;
        div.innerHTML =
          '<div class="skill-scope">' + (skrid ? skrid.iconSm : '') + esc(scopeLabel) + '</div>' +
          '<div class="skill-name">' + (s.kind === 'workflow' ? '' : '/') + esc(s.name) + kindBadge(s.kind) + '</div>';

        div.onclick = function() { loadSkill(s.id); };
        skillListEl.appendChild(div);
      });
    });
}

export function showSkillsHome() {
  fetch('/api/skills/')
    .then(r => r.json())
    .then(skillsList => {
      // Group by scope: global first, then per-repo
      var groups = {};
      var groupOrder = [];
      skillsList.forEach(s => {
        if (!groups[s.scope]) {
          groups[s.scope] = [];
          groupOrder.push(s.scope);
        }
        groups[s.scope].push(s);
      });

      // Put global first
      groupOrder.sort(function(a, b) {
        if (a === 'global') return -1;
        if (b === 'global') return 1;
        return a.localeCompare(b);
      });

      var container = document.getElementById('home-cols');
      if (!container) return;

      groupOrder.forEach(function(scope) {
        var skills = groups[scope];
        var isGlobal = scope === 'global';
        var short = isGlobal ? 'Global' : scope.replace(/^\/home\/[^/]+\//, '~/');
        var name = isGlobal ? 'Global' : short.split('/').pop();

        var col = document.createElement('div');
        col.className = 'home-column';
        var skrid2 = !isGlobal ? RepoIdentity.get(scope) : null;

        var header = document.createElement('div');
        header.className = 'home-column-header';
        if (skrid2) {
          header.style.background = skrid2.colorLight;
          col.style.borderTop = '3px solid ' + skrid2.colorBorder;
        }
        var nameDiv = document.createElement('div');
        nameDiv.innerHTML = (skrid2 ? skrid2.iconMd : '') + esc(name) + (!isGlobal ? '<span class="col-path">' + esc(short) + '</span>' : '');
        if (!isGlobal) nameDiv.title = scope;
        header.appendChild(nameDiv);
        col.appendChild(header);

        var list = document.createElement('div');
        list.className = 'home-conv-list';

        skills.forEach(function(s) {
          var item = document.createElement('div');
          item.className = 'home-conv-item';
          var meta = '<div class="conv-meta">';
          if (s.modified) meta += '<span>' + esc(formatDate(s.modified)) + '</span>';
          meta += '</div>';
          item.innerHTML = meta + '<div>' + (s.kind === 'workflow' ? '' : '/') + esc(s.name) + kindBadge(s.kind) + '</div>';
          item.onclick = function() { loadSkill(s.id); };
          list.appendChild(item);
        });

        col.appendChild(list);
        container.appendChild(col);
      });
    });
}

export function loadSkill(skillId, pushHistory) {
  setActiveScreen({ activeSkillId: skillId });
  document.querySelectorAll('.skill-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === skillId);
  });
  if (!skillListEl.children.length) loadSkillsSidebar();
  mainEl.innerHTML = '<div class="empty">Loading...</div>';

  fetch('/api/skills/' + skillId + '/')
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        mainEl.innerHTML = '<div class="empty">' + esc(data.error) + '</div>';
        return;
      }
      if (pushHistory !== false) {
        history.pushState({skillId: skillId}, '', skillDisplayUrl(data.scope, data.name));
      }

      var renderSkillView = function() {
        mainEl.innerHTML = '';

        var toolbar = document.createElement('div');
        toolbar.className = 'conversation-toolbar';
        toolbar.innerHTML = '<span class="header-btns"><span class="close-conv" title="Close">&times;</span></span>';
        toolbar.querySelector('.close-conv').onclick = function() { closeConversation('skills'); };
        mainEl.appendChild(toolbar);

        var header = document.createElement('div');
        header.className = 'conversation-header';
        header.style.borderLeft = '3px solid #0d9488';
        header.style.paddingLeft = '12px';
        var scopeLabel = data.scope === 'global' ? 'Global' : data.scope.replace(/^\/home\/[^/]+\//, '~/');
        header.innerHTML = '<span>' + (data.kind === 'workflow' ? '' : '/') + esc(data.name) + kindBadge(data.kind) + '</span><span>' + esc(scopeLabel) + '</span><span style="font-family:monospace;font-size:11px">' + esc(data.path) + '</span>';
        mainEl.appendChild(header);

        var view = document.createElement('div');
        view.className = 'skill-detail-view';

        var actions = document.createElement('div');
        actions.className = 'skill-actions';

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
            fetch('/api/skills/' + skillId + '/', {
              method: 'PUT',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({content: textarea.value})
            })
            .then(r => r.json().then(d => ({ok: r.ok, data: d})))
            .then(function(resp) {
              if (resp.ok) {
                loadSkill(skillId, false);
              } else {
                saveBtn.textContent = 'Error';
                setTimeout(function() { saveBtn.textContent = 'Save'; }, 2000);
              }
            });
          };
          actions.appendChild(saveBtn);

          var cancelBtn = document.createElement('button');
          cancelBtn.textContent = 'Cancel';
          cancelBtn.onclick = function() { loadSkill(skillId, false); };
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
          if (!confirm('Delete skill /' + data.name + '?')) return;
          fetch('/api/skills/' + skillId + '/', {method: 'DELETE'})
            .then(function() {
              loadSkillsSidebar();
              closeConversation('skills');
            });
        };
        actions.appendChild(deleteBtn);

        if (data.kind === 'workflow') {
          // no Run/Cron for workflows
        } else {
        var runWrap = document.createElement('div');
        runWrap.className = 'run-dropdown';
        var runBtn = document.createElement('button');
        runBtn.textContent = 'Run';
        if (data.scope === 'global') {
          runBtn.classList.add('has-dropdown');
          var runPanel = document.createElement('div');
          runPanel.className = 'run-dropdown-panel';
          runBtn.onclick = function() {
            if (runPanel.classList.contains('open')) {
              runPanel.classList.remove('open');
              return;
            }
            runPanel.innerHTML = '<button disabled style="color:#aaa">Loading...</button>';
            runPanel.classList.add('open');
            fetch('/api/conversations/')
              .then(r => r.json())
              .then(conversations => {
                var seen = {};
                var cwds = [];
                conversations.forEach(c => {
                  var p = c.project;
                  if (p && !seen[p]) {
                    seen[p] = true;
                    cwds.push(p);
                  }
                });
                runPanel.innerHTML = '';
                if (!cwds.length) {
                  runPanel.innerHTML = '<button disabled style="color:#aaa">No repos found</button>';
                  return;
                }
                cwds.forEach(cwd => {
                  var btn = document.createElement('button');
                  btn.textContent = cwd.replace(/^\/home\/[^/]+\//, '~/');
                  btn.title = cwd;
                  btn.onclick = function() {
                    runPanel.classList.remove('open');
                    runBtn.textContent = '...';
                    fetch('/api/sessions/new/', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({prompt: '/' + data.name, cwd: cwd})
                    })
                    .then(r => r.json().then(d => ({ok: r.ok, data: d})))
                    .then(function(resp) {
                      runBtn.textContent = resp.ok ? 'Launched' : 'Error';
                      runBtn.classList.add('has-dropdown');
                      setTimeout(function() { runBtn.textContent = 'Run'; }, 2000);
                    });
                  };
                  runPanel.appendChild(btn);
                });
              });
          };
          runWrap.appendChild(runBtn);
          runWrap.appendChild(runPanel);
        } else {
          runBtn.onclick = function() {
            runBtn.textContent = '...';
            fetch('/api/sessions/new/', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({prompt: '/' + data.name, cwd: data.scope})
            })
            .then(r => r.json().then(d => ({ok: r.ok, data: d})))
            .then(function(resp) {
              runBtn.textContent = resp.ok ? 'Launched' : 'Error';
              setTimeout(function() { runBtn.textContent = 'Run'; }, 2000);
            });
          };
          runWrap.appendChild(runBtn);
        }
        actions.appendChild(runWrap);

        var cronWrap = document.createElement('div');
        cronWrap.className = 'run-dropdown';
        var cronBtn = document.createElement('button');
        cronBtn.textContent = 'Cron';
        cronBtn.style.cssText = 'border-color:#fda4af;background:#fff1f2;color:#9f1239';
        var cronPanel = document.createElement('div');
        cronPanel.className = 'run-dropdown-panel';
        cronBtn.classList.add('loading');
        fetch('/api/cronjobs/')
          .then(function(r) { return r.json(); })
          .then(function(cronjobs) {
            cronBtn.classList.remove('loading');
            var matches = cronjobs.filter(function(cj) { return cj.skill_name === data.name; });
            if (matches.length === 0) {
              cronBtn.classList.add('has-plus');
              cronBtn.onclick = function() { showCreateCronjobForm(data.name); };
            } else {
              cronBtn.classList.add('has-dropdown');
              cronBtn.onclick = function() {
                if (cronPanel.classList.contains('open')) {
                  cronPanel.classList.remove('open');
                  return;
                }
                cronPanel.innerHTML = '';
                matches.forEach(function(cj) {
                  var btn = document.createElement('button');
                  var short = cj.repo.replace(/^\/home\/[^/]+\//, '~/');
                  btn.textContent = cj.schedule_summary + ' in ' + short;
                  btn.onclick = function() {
                    cronPanel.classList.remove('open');
                    loadCronjob(cj.id);
                  };
                  cronPanel.appendChild(btn);
                });
                var newBtn = document.createElement('button');
                newBtn.textContent = '+ New cronjob';
                newBtn.style.cssText = 'color:#9f1239;font-weight:600';
                newBtn.onclick = function() {
                  cronPanel.classList.remove('open');
                  showCreateCronjobForm(data.name);
                };
                cronPanel.appendChild(newBtn);
                cronPanel.classList.add('open');
              };
            }
          });
        cronWrap.appendChild(cronBtn);
        cronWrap.appendChild(cronPanel);
        actions.appendChild(cronWrap);
        }

        view.appendChild(actions);

        if (data.kind === 'workflow') {
          var meta = null;
          var metaMatch = data.content.match(/export\s+const\s+meta\s*=\s*(\{[\s\S]*?\n\})/);
          if (metaMatch) {
            try {
              var cleaned = metaMatch[1]
                .replace(/,(\s*[}\]])/g, '$1')
                .replace(/'/g, '"')
                .replace(/([{,])\s*(\w+)\s*:/g, '$1 "$2":');
              meta = JSON.parse(cleaned);
            } catch (e) { /* ignore */ }
          }
          if (meta) {
            var fmBlock = document.createElement('dl');
            fmBlock.className = 'skill-frontmatter';
            if (meta.description) {
              var dt = document.createElement('dt'); dt.textContent = 'description';
              var dd = document.createElement('dd'); dd.textContent = meta.description;
              fmBlock.appendChild(dt); fmBlock.appendChild(dd);
            }
            if (meta.whenToUse) {
              var dt2 = document.createElement('dt'); dt2.textContent = 'whenToUse';
              var dd2 = document.createElement('dd'); dd2.textContent = meta.whenToUse;
              fmBlock.appendChild(dt2); fmBlock.appendChild(dd2);
            }
            if (meta.phases && meta.phases.length) {
              var dt3 = document.createElement('dt'); dt3.textContent = 'phases';
              var dd3 = document.createElement('dd');
              dd3.innerHTML = meta.phases.map(function(p) {
                return '<div><strong>' + esc(p.title || '') + '</strong>' +
                  (p.detail ? ' — ' + esc(p.detail) : '') + '</div>';
              }).join('');
              fmBlock.appendChild(dt3); fmBlock.appendChild(dd3);
            }
            view.appendChild(fmBlock);
          }
          var contentBlock = document.createElement('div');
          contentBlock.className = 'block text';
          contentBlock.innerHTML = '<pre style="background:#f5f5f5;padding:12px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;font-size:12px">' + esc(data.content) + '</pre>';
          view.appendChild(contentBlock);
        } else {
          var body = data.content;
          var fmMatch = body.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
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
            body = fmMatch[2];
          }

          var contentBlock = document.createElement('div');
          contentBlock.className = 'block text';
          contentBlock.innerHTML = renderMarkdown(body);
          view.appendChild(contentBlock);
        }

        var invocSection = document.createElement('div');
        invocSection.className = 'skill-invocations';
        invocSection.innerHTML = '<h3 style="margin:24px 0 8px;font-size:14px;color:#888">Recent invocations</h3><div style="font-size:13px;color:#888">Loading...</div>';
        view.appendChild(invocSection);

        fetch('/api/skills/' + skillId + '/invocations/')
          .then(r => r.json())
          .then(function(invocations) {
            invocSection.innerHTML = '<h3 style="margin:24px 0 8px;font-size:14px;color:#888">Recent invocations</h3>';
            if (!invocations.length) {
              invocSection.innerHTML += '<div style="font-size:13px;color:#888">No invocations found.</div>';
              return;
            }
            var list = document.createElement('div');
            list.className = 'home-conv-list';
            invocations.forEach(function(inv) {
              var item = document.createElement('div');
              item.className = 'home-conv-item';
              item.style.cursor = 'pointer';
              var rid = inv.cwd ? RepoIdentity.get(inv.cwd) : null;
              var short = inv.cwd ? inv.cwd.replace(/^\/home\/[^/]+\//, '~/') : '';
              var ago = timeAgo(inv.timestamp);
              var meta = '<div class="conv-meta">' +
                '<span>' + esc(formatDate(inv.timestamp)) + (ago ? ' (' + esc(ago) + ')' : '') + '</span>' +
                '</div>';
              var repo = '<div style="display:flex;align-items:center;gap:6px">' +
                (rid ? rid.iconSm : '') +
                '<span' + (rid ? ' style="color:' + rid.colorText + '"' : '') + '>' + esc(short) + '</span>' +
                '<a href="/conversations/' + esc(inv.conversation_id) + '" style="color:#4338ca;margin-left:auto;flex-shrink:0">' + esc(inv.conversation_id.substring(0, 8)) + '...</a>' +
                '</div>';
              var summary = inv.summary ? '<div class="invoc-summary">' + renderMarkdown(inv.summary) + '</div>' : '';
              item.innerHTML = meta + repo + summary;
              item.onclick = function(e) {
                if (e.target.closest('a')) return;
                loadConversation(inv.conversation_id);
              };
              list.appendChild(item);
            });
            invocSection.appendChild(list);
          });

        mainEl.appendChild(view);
        renderRichBlocks();
        mainEl.scrollTop = 0;
        mainEl.focus();
      };

      renderSkillView();
    });
}

export function showCreateSkillForm(pushHistory) {
  setActiveScreen({ activeNewScreen: 'skill' });
  if (pushHistory !== false) {
    history.pushState(null, '', '/skills/new');
  }

  // Fetch skills to discover repo scopes
  fetch('/api/skills/')
    .then(r => r.json())
    .then(skillsList => {
      var scopes = ['global'];
      var seen = {global: true};
      skillsList.forEach(function(s) {
        if (s.scope !== 'global' && !seen[s.scope]) {
          seen[s.scope] = true;
          scopes.push(s.scope);
        }
      });

      mainEl.innerHTML = '';

      var toolbar = document.createElement('div');
      toolbar.className = 'conversation-toolbar';
      toolbar.innerHTML = '<span class="header-btns"><span class="close-conv" title="Close">&times;</span></span>';
      toolbar.querySelector('.close-conv').onclick = function() { closeConversation('skills'); };
      mainEl.appendChild(toolbar);

      var form = document.createElement('div');
      form.className = 'create-skill-form';
      form.innerHTML =
        '<h3 style="margin-bottom:12px">New skill</h3>' +
        '<div class="kind-options" id="cs-kind">' +
          '<label><input type="radio" name="cs-kind" value="command" checked> Command' +
            '<div class="kind-desc">.claude/commands/name.md — single markdown file</div></label>' +
          '<label><input type="radio" name="cs-kind" value="skill"> Skill' +
            '<div class="kind-desc">.claude/skills/name/SKILL.md — directory with SKILL.md</div></label>' +
        '</div>' +
        '<input type="text" id="cs-name" placeholder="skill-name (kebab-case)">' +
        '<div class="scope-options" id="cs-scopes"></div>' +
        '<textarea id="cs-content" placeholder="Skill content (markdown)..."></textarea>' +
        '<button id="cs-create">Create</button>' +
        '<span class="form-status" id="cs-status"></span>';
      mainEl.appendChild(form);

      var scopesEl = document.getElementById('cs-scopes');
      scopes.forEach(function(scope, i) {
        var label = document.createElement('label');
        var radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'cs-scope';
        radio.value = scope;
        if (i === 0) radio.checked = true;
        label.appendChild(radio);
        label.appendChild(document.createTextNode(' ' + (scope === 'global' ? 'Global' : scope.replace(/^\/home\/[^/]+\//, '~/'))));
        scopesEl.appendChild(label);
      });

      document.getElementById('cs-name').focus();

      document.getElementById('cs-create').onclick = function() {
        var name = document.getElementById('cs-name').value.trim();
        var content = document.getElementById('cs-content').value;
        var scope = document.querySelector('input[name="cs-scope"]:checked').value;
        var kind = document.querySelector('input[name="cs-kind"]:checked').value;
        var statusEl = document.getElementById('cs-status');

        if (!name || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(name)) {
          statusEl.textContent = 'Name must be kebab-case';
          return;
        }

        statusEl.textContent = 'Creating...';
        fetch('/api/skills/', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: name, scope: scope, kind: kind, content: content})
        })
        .then(r => r.json().then(d => ({ok: r.ok, data: d})))
        .then(function(resp) {
          if (resp.ok) {
            loadSkillsSidebar();
            loadSkill(resp.data.id);
          } else {
            statusEl.textContent = resp.data.error || 'Error';
          }
        });
      };
    });
}

// Skill URL helpers: display as /skills/global/name or /skills/~/repo/name
export function skillDisplayUrl(scope, name) {
  var scopeSlug = scope === 'global' ? 'global' : scope.replace(/^\/home\/[^/]+\//, '~/');
  return '/skills/' + encodeURIComponent(scopeSlug) + '/' + encodeURIComponent(name);
}

export function loadSkillByUrl(scopeSlug, name, pushHistory) {
  fetch('/api/skills/')
    .then(r => r.json())
    .then(skills => {
      var match = skills.find(s => {
        var slug = s.scope === 'global' ? 'global' : s.scope.replace(/^\/home\/[^/]+\//, '~/');
        return slug === scopeSlug && s.name === name;
      });
      if (match) loadSkill(match.id, pushHistory);
    });
}

export function navigateToSkillByName(name) {
  fetch('/api/skills/')
    .then(function(r) { return r.json(); })
    .then(function(skills) {
      var matches = skills.filter(function(s) { return s.name === name; });
      if (!matches.length) return;
      if (matches.length === 1) { loadSkill(matches[0].id); return; }
      if (currentCwd) {
        var cwdMatch = matches.find(function(s) {
          return s.scope !== 'global' && currentCwd.startsWith(s.scope);
        });
        if (cwdMatch) { loadSkill(cwdMatch.id); return; }
      }
      loadSkill(matches[0].id);
    });
}
