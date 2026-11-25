const $ = (id) => document.getElementById(id);
const id = location.pathname.split('/').filter(Boolean)[1];
const endpoint = `/api/report-actions/${id}`;
let proposal;
let sending = false;
let consumed = false;

function showError(message) {
  $('error').textContent = message;
  $('error').hidden = false;
}

function resultLink(parent, label, href) {
  const link = document.createElement('a');
  link.href = href;
  link.textContent = label;
  parent.append(link);
}

function updateButton() {
  $('submit').disabled =
    sending ||
    consumed ||
    !proposal?.can_submit ||
    !$('message').value.trim() ||
    (proposal.freshness.requires_acknowledgement && !$('ack').checked);
}

function render(p, keepMessage = false) {
  proposal = p;
  $('proposal').hidden = false;
  $('label').textContent = p.label;
  document.title = `${p.label} - Continue in Contexts`;
  const age = p.freshness;
  const heading = {
    recent: 'Recent report',
    aging: 'Report is getting older',
    stale: 'Stale report - review before continuing',
    old: 'Old report - assumptions may no longer hold',
  }[age.level];
  $('age').className = age.level;
  $('age').replaceChildren();
  const title = document.createElement('strong');
  title.textContent = `${heading}: ${age.days} day${age.days === 1 ? '' : 's'} old`;
  const date = document.createElement('p');
  date.textContent = `Report generated ${new Date(p.report_created_at).toLocaleString()} (${p.report_created_at}). ${age.days >= 3 ? "Check the findings and proposed message against today's project state." : 'Review the proposed message before confirming.'}`;
  $('age').append(title, date);
  $('details').replaceChildren();
  for (const [key, value] of [
    ['Report', p.title],
    ['Report file', p.report_path || 'Not recorded'],
    ['Project', p.project],
    ['Harness', p.source],
    ['Source session', p.conversation_id],
    ['Operation', 'Fork a separate follow-up'],
  ]) {
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = key;
    dd.textContent = value;
    $('details').append(dt, dd);
  }
  $('source').href = p.conversation_url;
  $('source-state').textContent = [
    p.source_active
      ? 'The source is live; it will be left untouched.'
      : 'The source is not currently detected as live.',
    p.source_changed
      ? 'The source conversation has changed since these actions were prepared. The fork will include its current history.'
      : '',
  ]
    .filter(Boolean)
    .join(' ');
  $('mode').textContent =
    p.mode === 'exclusive'
      ? 'Choose one alternative. Submitting any choice permanently consumes this choice group.'
      : 'These actions are independent. You can submit several, but each action runs at most once.';
  $('choices').replaceChildren();
  for (const choice of p.choices) {
    const li = document.createElement('li');
    resultLink(li, choice.label, choice.url);
    li.append(
      ` - ${choice.status}${choice.id === p.id ? ' (this action)' : ''}${choice.id === p.selected_action ? ' (selected choice)' : ''}`,
    );
    $('choices').append(li);
  }
  if (!keepMessage) $('message').value = p.submitted_text || p.text;
  $('message').readOnly = p.status !== 'pending';
  $('stale-ack').hidden = !age.requires_acknowledgement;
  const blocked = p.selected_action && p.selected_action !== p.id;
  const statuses = {
    submitting:
      'Already submitted. Launch is being processed, or its outcome is not yet known. Do not retry manually without checking.',
    submitted:
      'Already submitted. This action cannot run again. Submitted means the follow-up was launched, not that its work has finished.',
    uncertain:
      'Already submitted, but launch could not be confirmed. Inspect the session before doing anything manually. This action cannot run again.',
  };
  $('status').textContent = blocked
    ? 'Another choice in this group has already been submitted. This alternative will not run.'
    : statuses[p.status] ||
      p.problem ||
      'Not submitted. Confirming starts a separate conversation.';
  $('result').replaceChildren();
  if (p.result.conversation_id) {
    resultLink(
      $('result'),
      'Open follow-up conversation',
      `/conversations/${encodeURIComponent(p.result.conversation_id)}`,
    );
  } else if (p.result.session) {
    $('result').textContent =
      `Follow-up tmux session: ${p.result.session}. Open Contexts to find the paired conversation once the harness publishes it.`;
  }
  if (p.result.error) {
    const error = document.createElement('p');
    error.textContent = p.result.error;
    $('result').append(error);
  }
  updateButton();
}

async function load(keepMessage = false) {
  const response = await fetch(endpoint, { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || 'Could not load this saved action.');
  render(data, keepMessage);
}

$('ack').addEventListener('change', updateButton);
$('message').addEventListener('input', updateButton);
$('submit').addEventListener('click', async () => {
  if ($('submit').disabled) return;
  sending = true;
  updateButton();
  $('error').hidden = true;
  try {
    const response = await fetch(`${endpoint}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        confirm: 'fork',
        text: $('message').value,
        acknowledge_stale: $('ack').checked,
      }),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.error || 'Submission could not be confirmed.');
    consumed = true;
    await load();
  } catch (error) {
    showError(
      `${error.message} If delivery is uncertain, inspect the action status before doing anything manually.`,
    );
    // A failed response may have followed a successful claim. Never blindly resend.
    try {
      await load(true);
    } catch {
      consumed = true;
    }
  } finally {
    sending = false;
    updateButton();
  }
});
window.addEventListener('focus', () =>
  load(true).catch((error) => {
    consumed = true;
    showError(error.message);
    updateButton();
  }),
);
load().catch((error) => showError(error.message));
