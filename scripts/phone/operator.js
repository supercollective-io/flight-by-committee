const $ = selector => document.querySelector(selector);
let token = '';
async function refresh() {
  $('#feedback').textContent = 'Checking Flight…';
  $('#invitation').removeAttribute('href');
  for (const button of document.querySelectorAll('button')) button.disabled = true;
  try {
    const response = await fetch('/api/operator/sessions/current', {
      headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error(response.status === 401 ? 'Check the operator token and try again.' : 'Flight is unavailable. Try refreshing.');
    const flight = await response.json();
    const invitation = new URL(flight.participantUrl);
    if (invitation.origin !== location.origin || invitation.pathname !== '/' || !/^\?key=[A-Za-z0-9_-]{24,128}$/.test(invitation.search) || invitation.hash) throw new Error('Flight returned an invalid invitation.');
    $('#invitation').href = invitation.href;
    $('#status').textContent = { 'aircraft-ready': 'Aircraft ready', 'simulator-loading': 'Simulator loading', 'simulator-disconnected': 'Simulator disconnected — start FlightGear and its bridge.' }[flight.status] ?? 'Status unknown';
    $('#flight').hidden = false; $('#sign-in').hidden = true;
    $('#feedback').textContent = 'Invitation available. Check readiness again before cueing Flight.';
  } catch (error) { $('#feedback').textContent = error.message; $('#status').textContent = 'Current status unavailable'; }
  finally { for (const button of document.querySelectorAll('button')) button.disabled = false; }
}
$('#sign-in').addEventListener('submit', event => { event.preventDefault(); token = $('#token').value; $('#token').value = ''; void refresh(); });
$('#refresh').addEventListener('click', () => void refresh());
$('#sign-out').addEventListener('click', () => { token = ''; $('#flight').hidden = true; $('#sign-in').hidden = false; $('#invitation').removeAttribute('href'); $('#feedback').textContent = 'Signed out'; $('#token').focus(); });
