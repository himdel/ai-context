import { esc } from '/js/utils.js';

export let currentForgeRepo = null;
export let currentForgeOrigin = null;
export let currentPR = null;
export let currentCwd = null;

export function forgeRepoUrl(f) { return f.base_url + '/' + f.repo; }
export function forgeBranchUrl(f, branch) {
  if (f.type === 'gitlab') return forgeRepoUrl(f) + '/-/tree/' + encodeURIComponent(branch);
  if (f.type === 'gitea') return forgeRepoUrl(f) + '/src/branch/' + encodeURIComponent(branch);
  return forgeRepoUrl(f) + '/tree/' + encodeURIComponent(branch);
}
export function forgeCommitUrl(f, sha) {
  if (f.type === 'gitlab') return forgeRepoUrl(f) + '/-/commit/' + sha;
  return forgeRepoUrl(f) + '/commit/' + sha;
}
export function forgePrUrl(f, id) {
  if (f.type === 'gitlab') return forgeRepoUrl(f) + '/-/merge_requests/' + id;
  if (f.type === 'gitea') return forgeRepoUrl(f) + '/pulls/' + id;
  return forgeRepoUrl(f) + '/pull/' + id;
}
export function forgeName(f) {
  if (f.type === 'gitlab') return 'GitLab';
  if (f.type === 'gitea') return 'Gitea';
  return 'GitHub';
}

export function setForgeAutolink(gh) {
  currentForgeRepo = (gh && gh.upstream) || (gh && gh.origin);
  currentForgeOrigin = (gh && gh.origin) || (gh && gh.upstream);
  currentPR = gh && gh.pr;
}

export function setCurrentCwd(cwd) {
  currentCwd = cwd;
}

export function linkifyForge(html) {
  if (currentForgeRepo && currentForgeRepo.type !== 'gitlab') {
    html = html.replace(/(^|[>\s(])#(\d+)\b/g, function(match, before, id) {
      return before + '<a href="' + esc(forgePrUrl(currentForgeRepo, id)) + '" target="_blank" rel="noopener noreferrer">#' + id + '</a>';
    });
  }
  if (currentForgeRepo && currentForgeRepo.type === 'gitlab') {
    html = html.replace(/(^|[>\s(])!(\d+)\b/g, function(match, before, id) {
      return before + '<a href="' + esc(forgePrUrl(currentForgeRepo, id)) + '" target="_blank" rel="noopener noreferrer">!' + id + '</a>';
    });
  }
  html = html.replace(/<code>([0-9a-f]{7})<\/code>/g, function(match, sha) {
    var link = '<code><a href="#" class="git-show-link" data-sha="' + sha + '">' + sha + '</a></code>';
    if (currentForgeRepo) {
      link += '<a href="' + esc(forgeCommitUrl(currentForgeRepo, sha)) + '" target="_blank" rel="noopener noreferrer" class="exticon" title="View on ' + forgeName(currentForgeRepo) + '">&#x2197;</a>';
    }
    return link;
  });
  return html;
}
