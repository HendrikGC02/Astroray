/**
 * Astroray project tracker — Google Apps Script
 *
 * Pulls live data from the public GitHub repo and rebuilds every dynamic
 * sheet. Safe to re-run; it preserves the spreadsheet itself and only
 * touches its known sheets.
 *
 * One-time setup:
 *   1. Open your spreadsheet → Extensions → Apps Script.
 *   2. Replace Code.gs contents with this file.
 *   3. Save.
 *   4. Run setup()  — Apps Script will ask for permission the first time
 *      (UrlFetchApp + SpreadsheetApp). Approve.
 *   5. Optional: run installDailyTrigger() to auto-refresh once a day.
 *
 * After that, the spreadsheet has a "Astroray" menu in the menu bar with
 * "Refresh now" + trigger management.
 */

// ───────────── Config ─────────────

const REPO   = 'HendrikGC02/Astroray';
const BRANCH = 'main';

// Optional: paste a GitHub PAT (no scopes needed for a public repo) to
// raise the rate limit from 60/hr → 5000/hr. Safe-ish to leave blank.
const GITHUB_TOKEN = '';

// Sheet names (used by setup + refresh).
const S = {
  dashboard: 'Dashboard',
  packages : 'Packages',
  pillars  : 'Pillars',
  prs      : 'PRs (open)',
  issues   : 'Issues (open)',
  commits  : 'Commits',
  timeline : 'Timeline',
  about    : 'About',
};

// ───────────── Menu ─────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Astroray')
    .addItem('Refresh now', 'refresh')
    .addSeparator()
    .addItem('Run full setup', 'setup')
    .addSeparator()
    .addItem('Install daily auto-refresh', 'installDailyTrigger')
    .addItem('Remove auto-refresh', 'removeDailyTrigger')
    .addToUi();
}

// ───────────── Top-level entry points ─────────────

/** Build every sheet from scratch and pull live data. */
function setup() {
  const ss = SpreadsheetApp.getActive();
  ensureSheets_(ss);
  buildAbout_(ss);
  buildPillars_(ss);            // static structure; counts come from Packages
  refresh();                     // pulls everything else
  buildDashboard_(ss);          // links + summary formulas (must run after Packages exists)
  // Reorder sheets, hide nothing.
  reorderSheets_(ss);
  ss.setActiveSheet(ss.getSheetByName(S.dashboard));
  toast_('Setup complete.');
}

/** Refresh all live data (Packages, PRs, Issues, Commits, Timeline). */
function refresh() {
  const ss = SpreadsheetApp.getActive();
  ensureSheets_(ss);
  refreshPackages_(ss);
  refreshPRs_(ss);
  refreshIssues_(ss);
  refreshCommits_(ss);
  refreshTimeline_(ss);
  stampAbout_(ss);
  toast_('Refreshed.');
}

function installDailyTrigger() {
  removeDailyTrigger();
  ScriptApp.newTrigger('refresh').timeBased().everyDays(1).atHour(7).create();
  toast_('Auto-refresh installed: daily at 7am.');
}

function removeDailyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'refresh')
    .forEach(t => ScriptApp.deleteTrigger(t));
}

// ───────────── Sheet scaffolding ─────────────

function ensureSheets_(ss) {
  Object.values(S).forEach(name => {
    if (!ss.getSheetByName(name)) ss.insertSheet(name);
  });
  // If the default "Sheet1" exists and we have our named sheets, drop it.
  const def = ss.getSheetByName('Sheet1');
  if (def && Object.values(S).every(n => ss.getSheetByName(n))) {
    ss.deleteSheet(def);
  }
}

function reorderSheets_(ss) {
  const order = [S.dashboard, S.packages, S.pillars, S.prs, S.issues,
                 S.commits, S.timeline, S.about];
  order.forEach((name, idx) => {
    const sh = ss.getSheetByName(name);
    if (sh) ss.setActiveSheet(sh) && ss.moveActiveSheet(idx + 1);
  });
}

// ───────────── Dashboard ─────────────

function buildDashboard_(ss) {
  const sh = ss.getSheetByName(S.dashboard);
  sh.clear();

  sh.getRange('A1').setValue('Astroray Project Tracker')
    .setFontSize(18).setFontWeight('bold');
  sh.getRange('A2').setFormula(`="Last refreshed: " & TEXT('${S.about}'!B2, "yyyy-mm-dd hh:mm")`)
    .setFontColor('#666');

  // KPI band
  const kpis = [
    ['Pillar 1',  `=COUNTIFS('${S.packages}'!C:C, 1, '${S.packages}'!D:D, "done") & "/" & COUNTIF('${S.packages}'!C:C, 1)`],
    ['Pillar 2',  `=COUNTIFS('${S.packages}'!C:C, 2, '${S.packages}'!D:D, "done") & "/" & COUNTIF('${S.packages}'!C:C, 2)`],
    ['Pillar 3',  `=COUNTIFS('${S.packages}'!C:C, 3, '${S.packages}'!D:D, "done") & "/" & COUNTIF('${S.packages}'!C:C, 3)`],
    ['Pillar 4',  `=COUNTIFS('${S.packages}'!C:C, 4, '${S.packages}'!D:D, "done") & "/" & COUNTIF('${S.packages}'!C:C, 4)`],
    ['Pillar 5',  `=COUNTIFS('${S.packages}'!C:C, 5, '${S.packages}'!D:D, "done") & "/" & COUNTIF('${S.packages}'!C:C, 5)`],
    ['Open PRs',  `=COUNTA('${S.prs}'!A2:A)`],
    ['Open issues', `=COUNTA('${S.issues}'!A2:A)`],
    ['Total packages', `=COUNTA('${S.packages}'!A2:A)`],
  ];
  sh.getRange(4, 1, 1, kpis.length).setValues([kpis.map(k => k[0])])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white').setHorizontalAlignment('center');
  sh.getRange(5, 1, 1, kpis.length).setFormulas([kpis.map(k => k[1])])
    .setFontSize(14).setHorizontalAlignment('center').setBackground('#e8f0fe');
  sh.setRowHeight(5, 36);

  // Strategic gate banner
  sh.getRange('A8').setValue('Strategic gate').setFontWeight('bold').setBackground('#fbbc04');
  sh.getRange('B8').setValue('RELEASED 2026-05-10 — pkg56 Phase C (PR #233). Pillar 4 actively shipping.');
  sh.getRange('B8').setBackground('#fff8e1');

  // "What's hot" — open packages, top 15
  sh.getRange('A10').setValue("What's open right now (not done)").setFontWeight('bold');
  sh.getRange('A11').setFormula(
    `=QUERY('${S.packages}'!A:F, "select A,B,C,D,F where D <> 'done' order by C, A limit 20", 1)`
  );

  // Pillar mini-table mirror
  sh.getRange('H10').setValue('Pillar progress').setFontWeight('bold');
  sh.getRange('H11').setFormula(`='${S.pillars}'!A1`);
  sh.getRange('H11:K17').setFormula(`='${S.pillars}'!A1:D7`);

  // Recent activity preview
  sh.getRange('A33').setValue('Recent commits (last 10)').setFontWeight('bold');
  sh.getRange('A34').setFormula(
    `=QUERY('${S.commits}'!A:D, "select A,B,C,D limit 10", 1)`
  );

  // Open PRs preview
  sh.getRange('H33').setValue('Open PRs').setFontWeight('bold');
  sh.getRange('H34').setFormula(
    `=QUERY('${S.prs}'!A:E, "select A,B,C,D,E", 1)`
  );

  // Layout polish
  sh.setColumnWidth(1, 80);
  sh.setColumnWidth(2, 380);
  sh.setColumnWidth(3, 70);
  sh.setColumnWidth(4, 110);
  sh.setColumnWidth(5, 140);
  sh.setColumnWidth(6, 240);
  sh.setColumnWidth(8, 100);
  sh.setColumnWidth(9, 360);
  sh.setColumnWidth(10, 70);
  sh.setColumnWidth(11, 110);
  sh.setHiddenGridlines(true);
  sh.setFrozenRows(2);
}

// ───────────── Pillars ─────────────

function buildPillars_(ss) {
  const sh = ss.getSheetByName(S.pillars);
  sh.clear();
  const header = ['Pillar', 'Name', 'Done', '%'];
  const rows = [
    [1, 'Plugin architecture',                    '', ''],
    [2, 'Spectral core',                          '', ''],
    [3, 'Light transport',                        '', ''],
    [4, 'Astrophysics platform',                  '', ''],
    [5, 'Production polish / Blender parity',     '', ''],
  ];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');
  sh.getRange(2, 1, rows.length, rows[0].length).setValues(rows);
  for (let i = 0; i < rows.length; i++) {
    const p = rows[i][0];
    const r = i + 2;
    sh.getRange(r, 3).setFormula(
      `=COUNTIFS('${S.packages}'!C:C, ${p}, '${S.packages}'!D:D, "done") & "/" & COUNTIF('${S.packages}'!C:C, ${p})`
    );
    sh.getRange(r, 4).setFormula(
      `=IFERROR(COUNTIFS('${S.packages}'!C:C, ${p}, '${S.packages}'!D:D, "done")/COUNTIF('${S.packages}'!C:C, ${p}), 0)`
    ).setNumberFormat('0%');
  }
  // Conditional formatting on the % column
  const pctRange = sh.getRange(2, 4, rows.length, 1);
  const rules = sh.getConditionalFormatRules();
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .setGradientMaxpointWithValue('#34a853', SpreadsheetApp.InterpolationType.NUMBER, '1')
      .setGradientMidpointWithValue('#fbbc04', SpreadsheetApp.InterpolationType.NUMBER, '0.5')
      .setGradientMinpointWithValue('#ea4335', SpreadsheetApp.InterpolationType.NUMBER, '0')
      .setRanges([pctRange]).build()
  );
  sh.setConditionalFormatRules(rules);
  sh.setColumnWidths(1, 1, 70);
  sh.setColumnWidths(2, 1, 280);
  sh.setColumnWidths(3, 1, 90);
  sh.setColumnWidths(4, 1, 90);
  sh.setFrozenRows(1);
}

// ───────────── Packages ─────────────

function refreshPackages_(ss) {
  const sh = ss.getSheetByName(S.packages);
  sh.clear();
  const header = ['Package', 'Title', 'Pillar', 'Status', 'Effort', 'Path'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  // List package files via the GitHub API.
  const list = githubJson_(`/repos/${REPO}/contents/.astroray_plan/packages?ref=${BRANCH}`);
  if (!Array.isArray(list)) {
    sh.getRange('A2').setValue('Error fetching packages: ' + JSON.stringify(list));
    return;
  }
  const files = list.filter(f => f.name.endsWith('.md') && /^pkg/i.test(f.name));
  files.sort(byPkgKey_);

  const rows = files.map(f => {
    const text = httpGet_(rawUrl_(f.path));
    const meta = parsePackageMd_(text || '');
    const pkg = (f.name.match(/^pkg([0-9a-z-]+)/i) || [])[1] || '';
    const title = meta.title || f.name.replace(/\.md$/, '');
    const repoUrl = `https://github.com/${REPO}/blob/${BRANCH}/${f.path}`;
    return [
      `=HYPERLINK("${repoUrl}", "pkg${pkg}")`,
      title,
      meta.pillar || '',
      meta.status || '',
      meta.effort || '',
      f.path,
    ];
  });

  if (rows.length) {
    sh.getRange(2, 1, rows.length, header.length).setValues(rows);
  }

  // Status colour-coding
  const statusRange = sh.getRange(2, 4, Math.max(1, rows.length), 1);
  const rules = [];
  const tint = (kw, bg) =>
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextContains(kw).setBackground(bg).setRanges([statusRange]).build();
  rules.push(tint('done',         '#c8e6c9'));
  rules.push(tint('implemented',  '#fff9c4'));
  rules.push(tint('research',     '#ffe0b2'));
  rules.push(tint('open',         '#ffcdd2'));
  sh.setConditionalFormatRules(rules);

  sh.setColumnWidths(1, 1, 80);
  sh.setColumnWidths(2, 1, 380);
  sh.setColumnWidths(3, 1, 70);
  sh.setColumnWidths(4, 1, 280);
  sh.setColumnWidths(5, 1, 160);
  sh.setColumnWidths(6, 1, 380);
  sh.setFrozenRows(1);
  sh.getDataRange().createFilter();
}

/** Tolerant package-frontmatter parser. Reads only the first ~80 lines. */
function parsePackageMd_(md) {
  const lines = md.split(/\r?\n/).slice(0, 80);
  const meta = { title: '', pillar: '', status: '', effort: '' };
  for (const raw of lines) {
    const line = raw.trim();
    if (!meta.title && /^#\s+/.test(line)) {
      meta.title = line.replace(/^#\s+/, '').replace(/^pkg[0-9a-z-]+\s*[—\-:]\s*/i, '').trim();
      continue;
    }
    const mPillar = line.match(/^\*\*Pillar:\*\*\s*(.+)$/i);
    if (mPillar && !meta.pillar) {
      // Take the first digit we find: "2 (follow-up) / 5" → 2
      const d = mPillar[1].match(/\d+/);
      meta.pillar = d ? Number(d[0]) : mPillar[1].trim();
      continue;
    }
    const mStatus = line.match(/^\*\*Status:\*\*\s*(.+)$/i);
    if (mStatus && !meta.status) {
      meta.status = stripMd_(mStatus[1]).trim();
      continue;
    }
    const mEffort = line.match(/^\*\*Estimated effort:\*\*\s*(.+)$/i);
    if (mEffort && !meta.effort) {
      meta.effort = stripMd_(mEffort[1]).trim();
      continue;
    }
  }
  // Normalise the canonical statuses we colour-code on.
  const s = meta.status.toLowerCase();
  if (/(^|[^a-z])done([^a-z]|$)/.test(s) || /^complete\b/.test(s)) meta.status = 'done';
  else if (/^implemented\b/.test(s))                                meta.status = 'implemented';
  else if (/research/.test(s) && /(blocked|signed off|signed-off|signoff|sign\-off)/.test(s)) meta.status = 'research signed off';
  else if (/^open\b/.test(s))                                       meta.status = 'open';
  return meta;
}

function stripMd_(s) {
  return s.replace(/\*\*/g, '').replace(/`/g, '').replace(/\s+/g, ' ');
}

function byPkgKey_(a, b) {
  const ka = pkgKey_(a.name), kb = pkgKey_(b.name);
  if (ka.n !== kb.n) return ka.n - kb.n;
  return ka.suf < kb.suf ? -1 : ka.suf > kb.suf ? 1 : 0;
}

function pkgKey_(name) {
  const m = name.match(/^pkg(\d+)([a-z\-0-9]*)/i);
  if (!m) return { n: 9999, suf: name };
  return { n: Number(m[1]), suf: (m[2] || '').toLowerCase() };
}

// ───────────── PRs ─────────────

function refreshPRs_(ss) {
  const sh = ss.getSheetByName(S.prs);
  sh.clear();
  const header = ['#', 'Title', 'Author', 'Updated', 'Mergeable', 'URL'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  const prs = githubJson_(`/repos/${REPO}/pulls?state=open&per_page=50&sort=updated&direction=desc`);
  if (!Array.isArray(prs)) {
    sh.getRange('A2').setValue('Error: ' + JSON.stringify(prs));
    return;
  }
  const rows = prs.map(p => [
    `=HYPERLINK("${p.html_url}", "#${p.number}")`,
    p.title,
    p.user && p.user.login || '',
    new Date(p.updated_at),
    p.draft ? 'draft' : 'open',
    p.html_url,
  ]);
  if (rows.length) sh.getRange(2, 1, rows.length, header.length).setValues(rows);
  sh.getRange(2, 4, Math.max(1, rows.length), 1).setNumberFormat('yyyy-mm-dd hh:mm');
  sh.setColumnWidths(1, 1, 70);
  sh.setColumnWidths(2, 1, 460);
  sh.setColumnWidths(3, 1, 140);
  sh.setColumnWidths(4, 1, 150);
  sh.setColumnWidths(5, 1, 90);
  sh.setColumnWidths(6, 1, 360);
  sh.setFrozenRows(1);
  sh.getDataRange().createFilter();
}

// ───────────── Issues ─────────────

function refreshIssues_(ss) {
  const sh = ss.getSheetByName(S.issues);
  sh.clear();
  const header = ['#', 'Title', 'Labels', 'Updated', 'URL'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  const items = githubJson_(`/repos/${REPO}/issues?state=open&per_page=50&sort=updated&direction=desc`);
  if (!Array.isArray(items)) {
    sh.getRange('A2').setValue('Error: ' + JSON.stringify(items));
    return;
  }
  // Filter out PRs (the issues endpoint includes them)
  const issues = items.filter(i => !i.pull_request);
  const rows = issues.map(i => [
    `=HYPERLINK("${i.html_url}", "#${i.number}")`,
    i.title,
    (i.labels || []).map(l => l.name).join(', '),
    new Date(i.updated_at),
    i.html_url,
  ]);
  if (rows.length) sh.getRange(2, 1, rows.length, header.length).setValues(rows);
  sh.getRange(2, 4, Math.max(1, rows.length), 1).setNumberFormat('yyyy-mm-dd hh:mm');
  sh.setColumnWidths(1, 1, 70);
  sh.setColumnWidths(2, 1, 460);
  sh.setColumnWidths(3, 1, 180);
  sh.setColumnWidths(4, 1, 150);
  sh.setColumnWidths(5, 1, 360);
  sh.setFrozenRows(1);
  sh.getDataRange().createFilter();
}

// ───────────── Commits ─────────────

function refreshCommits_(ss) {
  const sh = ss.getSheetByName(S.commits);
  sh.clear();
  const header = ['SHA', 'Message', 'Author', 'When'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  const commits = githubJson_(`/repos/${REPO}/commits?per_page=60&sha=${BRANCH}`);
  if (!Array.isArray(commits)) {
    sh.getRange('A2').setValue('Error: ' + JSON.stringify(commits));
    return;
  }
  const rows = commits.map(c => {
    const sha = (c.sha || '').slice(0, 7);
    const msg = (c.commit && c.commit.message || '').split('\n')[0];
    const url = c.html_url;
    return [
      `=HYPERLINK("${url}", "${sha}")`,
      msg,
      c.commit && c.commit.author && c.commit.author.name || '',
      c.commit && c.commit.author && new Date(c.commit.author.date) || '',
    ];
  });
  if (rows.length) sh.getRange(2, 1, rows.length, header.length).setValues(rows);
  sh.getRange(2, 4, Math.max(1, rows.length), 1).setNumberFormat('yyyy-mm-dd hh:mm');
  sh.setColumnWidths(1, 1, 90);
  sh.setColumnWidths(2, 1, 560);
  sh.setColumnWidths(3, 1, 160);
  sh.setColumnWidths(4, 1, 150);
  sh.setFrozenRows(1);
  sh.getDataRange().createFilter();
}

// ───────────── Timeline ─────────────
//
// Parses the Changelog section of STATUS.md into one row per dated entry.

function refreshTimeline_(ss) {
  const sh = ss.getSheetByName(S.timeline);
  sh.clear();
  const header = ['Date', 'Summary'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  const md = httpGet_(rawUrl_('.astroray_plan/docs/STATUS.md'));
  if (!md) {
    sh.getRange('A2').setValue('Error fetching STATUS.md');
    return;
  }
  const idx = md.indexOf('## Changelog');
  const tail = idx >= 0 ? md.slice(idx) : md;

  // Split into bullet entries that start with "- **YYYY-MM-DD"
  const entries = [];
  const re = /\n-\s+\*\*(\d{4}-\d{2}-\d{2})[^*]*\*\*\s*([\s\S]*?)(?=\n-\s+\*\*\d{4}-\d{2}-\d{2}|\n## |\n---|$)/g;
  let m;
  while ((m = re.exec(tail))) {
    const date = m[1];
    const summary = m[2].replace(/\s+/g, ' ').trim();
    entries.push([new Date(date), summary.length > 600 ? summary.slice(0, 600) + '…' : summary]);
  }
  // Newest first
  entries.sort((a, b) => b[0] - a[0]);
  if (entries.length) sh.getRange(2, 1, entries.length, 2).setValues(entries);
  sh.getRange(2, 1, Math.max(1, entries.length), 1).setNumberFormat('yyyy-mm-dd');
  sh.setColumnWidths(1, 1, 110);
  sh.setColumnWidths(2, 1, 900);
  sh.setFrozenRows(1);
  sh.getDataRange().createFilter();
}

// ───────────── About ─────────────

function buildAbout_(ss) {
  const sh = ss.getSheetByName(S.about);
  sh.clear();
  const rows = [
    ['Repository',     `=HYPERLINK("https://github.com/${REPO}", "${REPO}")`],
    ['Last refreshed', ''],
    ['Branch',         BRANCH],
    ['STATUS.md',      `=HYPERLINK("https://github.com/${REPO}/blob/${BRANCH}/.astroray_plan/docs/STATUS.md", "STATUS.md")`],
    ['ROADMAP.md',     `=HYPERLINK("https://github.com/${REPO}/blob/${BRANCH}/.astroray_plan/docs/ROADMAP.md", "ROADMAP.md")`],
    ['NEXT_STAGE_REPORT.md',
      `=HYPERLINK("https://github.com/${REPO}/blob/${BRANCH}/.astroray_plan/docs/NEXT_STAGE_REPORT.md", "NEXT_STAGE_REPORT.md")`],
    ['Open PRs',       `=HYPERLINK("https://github.com/${REPO}/pulls", "see PRs tab")`],
    ['Open issues',    `=HYPERLINK("https://github.com/${REPO}/issues", "see Issues tab")`],
    ['', ''],
    ['How to refresh', 'Use the Astroray menu → Refresh now, or run installDailyTrigger() once.'],
    ['Source script',  'See test_results/astroray_dashboard.gs in the repo working tree (gitignored).'],
  ];
  sh.getRange(1, 1, rows.length, 2).setValues(rows);
  sh.getRange('A1:A' + rows.length).setFontWeight('bold');
  sh.setColumnWidths(1, 1, 180);
  sh.setColumnWidths(2, 1, 520);
}

function stampAbout_(ss) {
  const sh = ss.getSheetByName(S.about);
  sh.getRange('B2').setValue(new Date()).setNumberFormat('yyyy-mm-dd hh:mm');
}

// ───────────── HTTP helpers ─────────────

function rawUrl_(path) {
  return `https://raw.githubusercontent.com/${REPO}/${BRANCH}/${path}`;
}

function httpGet_(url) {
  const opts = { muteHttpExceptions: true, followRedirects: true };
  if (GITHUB_TOKEN && /api\.github\.com/.test(url)) {
    opts.headers = { Authorization: 'Bearer ' + GITHUB_TOKEN, 'X-GitHub-Api-Version': '2022-11-28' };
  }
  const resp = UrlFetchApp.fetch(url, opts);
  const code = resp.getResponseCode();
  if (code >= 200 && code < 300) return resp.getContentText();
  return '';
}

function githubJson_(path) {
  const url = path.startsWith('http') ? path : 'https://api.github.com' + path;
  const opts = {
    muteHttpExceptions: true,
    followRedirects: true,
    headers: { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
  };
  if (GITHUB_TOKEN) opts.headers.Authorization = 'Bearer ' + GITHUB_TOKEN;
  const resp = UrlFetchApp.fetch(url, opts);
  const code = resp.getResponseCode();
  const txt = resp.getContentText();
  if (code >= 200 && code < 300) {
    try { return JSON.parse(txt); } catch (e) { return { error: 'parse', body: txt.slice(0, 200) }; }
  }
  return { error: code, body: txt.slice(0, 400) };
}

// ───────────── UI ─────────────

function toast_(msg) {
  try { SpreadsheetApp.getActive().toast(msg, 'Astroray', 5); } catch (e) {}
}
