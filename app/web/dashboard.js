(() => {
  const element = id => document.getElementById(id);
  let data = null;
  let generation = 0;
  let historyStudent = null;
  const percent = value => value === null ? '—' : `${value.toFixed(1)}%`;
  function query() {
    return new URLSearchParams({month:element('dashboard-month').value,
      class_id:element('dashboard-class').value, subject_id:element('dashboard-subject').value});
  }
  function options(id, entries, title) {
    const select = element(id), previous = select.value;
    select.innerHTML = `<option value="">${title}</option>` + entries.map(row =>
      `<option value="${escapeHTML(row.id)}">${escapeHTML(row.name)}</option>`).join('');
    select.value = entries.some(row => row.id === previous) ? previous : '';
  }
  function subjects() {
    if (!data) return;
    const group = element('dashboard-class').value;
    options('dashboard-subject', data.subjects.filter(row => row.id && (!group || row.class_id === group)), 'All subjects');
  }
  async function load() {
    const version = ++generation;
    element('dashboard-message').textContent = 'Loading attendance…';
    element('dashboard-content').hidden = true;
    element('dashboard-export').hidden = true;
    try {
      const response = await api('/api/dashboard?' + query());
      if (version !== generation) return;
      data = response;
      options('dashboard-month',data.months.map(month => ({id:month,name:month})), 'All months');
      options('dashboard-class',data.classes,'All classes');
      subjects();
      element('dashboard-target').value = data.target;
      const warnings = [];
      if (data.skipped) warnings.push(`${data.skipped} unreadable lecture record(s) were excluded. Totals may be incomplete.`);
      if (!data.lectures) warnings.push('No finalized lectures match these filters. Finalize a lecture to see attendance here.');
      element('dashboard-message').textContent = warnings.join(' ');
      const month = element('dashboard-month').value;
      element('dashboard-export').hidden = !month;
      element('dashboard-export').href = '/api/dashboard/monthly.csv?' + query();
      element('dashboard-export-hint').hidden = Boolean(month);
      const below = data.students.filter(row => row.below_target).length;
      element('dashboard-stats').innerHTML = [[data.lectures,'Finalized lectures'],[percent(data.percentage),'Overall attendance'],[below,'Students below target']].map(([value,label]) =>
        `<div class="overview-card"><div><strong class="metric">${value}</strong><span class="metric-label">${label}</span></div></div>`).join('');
      for (const [id, rows] of [['classes',data.class_totals],['subjects',data.subject_totals],['weekly',data.weekly],['monthly',data.monthly]]) {
        element('dashboard-' + id).innerHTML = rows.length ? rows.map(row =>
          `<div class="dashboard-bar"><div><strong>${escapeHTML(row.label)}</strong><span>${percent(row.percentage)} · ${row.present}/${row.total} present</span></div><progress max="100" value="${row.percentage}" aria-label="${escapeHTML(row.label)} attendance">${percent(row.percentage)}</progress></div>`).join('') : '<p class="empty-state">No finalized attendance yet.</p>';
      }
      renderStudents();
      if (historyStudent && element('dashboard-history-dialog').open) showHistory(historyStudent);
      element('dashboard-content').hidden = false;
    } catch (error) {
      if (version === generation) element('dashboard-message').textContent = error.message;
    }
  }
  function renderStudents() {
    if (!data) return;
    const search = element('dashboard-search').value.trim().toLowerCase();
    const rows = data.students.filter(row => (!element('dashboard-below').checked || row.below_target) &&
      `${row.name} ${row.roll_number}`.toLowerCase().includes(search));
    element('dashboard-students').innerHTML = rows.map(row =>
      `<tr><td><strong>${escapeHTML(row.name)}</strong><small>Roll ${escapeHTML(row.roll_number)}</small></td><td>${row.present}/${row.total}</td><td>${row.total-row.present}</td><td>${percent(row.percentage)}</td><td><span class="status-pill ${row.below_target ? 'Review' : 'Present'}">${row.below_target ? 'Below target' : 'Meets target'}</span></td><td><button class="button secondary" data-student-history="${escapeHTML(row.identity)}">View history</button></td></tr>`).join('') || '<tr><td colspan="6">No students match these filters.</td></tr>';
  }
  function showHistory(identity) {
    historyStudent = identity;
    const student = data.students.find(row => row.identity === identity);
    if (!student) { element('dashboard-history-dialog').close(); return; }
    element('dashboard-history-title').textContent = `${student.name} · Roll ${student.roll_number}`;
    element('dashboard-history-summary').textContent = `${student.present} of ${student.total} lectures · ${percent(student.percentage)} attendance`;
    element('dashboard-history-rows').innerHTML = student.history.map(row =>
      `<tr><td>${escapeHTML(row.date)} ${escapeHTML(row.time)}</td><td>${escapeHTML(row.title)}<small>${escapeHTML(row.class_name)} · ${escapeHTML(row.subject_name)}</small></td><td>${escapeHTML(row.roll_number)}</td><td><span class="status-pill ${row.status}">${row.status}</span></td><td>${escapeHTML(row.note)}</td></tr>`).join('');
    if (!element('dashboard-history-dialog').open) element('dashboard-history-dialog').showModal();
  }
  window.refreshDashboard = () => { if (!element('page-dashboard').hidden) load(); };
  document.querySelector('[data-page="dashboard"]').addEventListener('click',load);
  element('dashboard-refresh').addEventListener('click',load);
  element('dashboard-month').addEventListener('change',load);
  element('dashboard-class').addEventListener('change',() => { element('dashboard-subject').value=''; subjects(); load(); });
  element('dashboard-subject').addEventListener('change',load);
  element('dashboard-search').addEventListener('input',renderStudents);
  element('dashboard-below').addEventListener('change',renderStudents);
  element('dashboard-students').addEventListener('click',event => {
    const button = event.target.closest('[data-student-history]');
    if (button) showHistory(button.dataset.studentHistory);
  });
  element('dashboard-history-close').addEventListener('click',() => element('dashboard-history-dialog').close());
  element('dashboard-target-form').addEventListener('submit',async event => {
    event.preventDefault();
    element('dashboard-target-save').disabled = true;
    try {
      await api('/api/dashboard',{target:Number(element('dashboard-target').value)});
      await load();
    } catch(error) { element('dashboard-message').textContent = error.message; }
    finally { element('dashboard-target-save').disabled = false; }
  });
})();
