/**
 * Astroray project tracker — standalone Google Apps Script.
 *
 * One-time setup:
 *   1. https://script.google.com/u/0/home → New project
 *   2. Paste this whole file into Code.gs (replace the default).
 *   3. Save (Ctrl+S).
 *   4. Run setup() from the editor. Approve permissions on first prompt.
 *   5. Open the Logger (View → Logs / Ctrl+Enter) to copy the Sheet URL.
 *   6. Optional: run installDailyTrigger() once to auto-refresh at 7am.
 *
 * Re-running setup() is safe — it reuses the existing Sheet (its ID is
 * stored in script properties).
 */

// ───────────── Config ─────────────

const REPO   = 'HendrikGC02/Astroray';
const BRANCH = 'main';

// Optional: paste a GitHub PAT (no scopes needed for a public repo) to
// raise the rate limit from 60/hr → 5000/hr. Safe-ish to leave blank.
const GITHUB_TOKEN = '';  // paste a PAT locally; do not commit

const SHEET_TITLE = 'Astroray Project Tracker';

// Strategic gate banner shown on the Dashboard. Edit this in one place
// instead of digging through the dashboard builder.
const STRATEGIC_GATE = 'Integration Milestone complete 2026-08 (pkg175–pkg178: Blender native-Principled + thin-film). Pillar 4 PAUSED pending owner go-ahead; integration-first directive in force.';

// Statuses that should NOT count toward the pillar denominator. Specs in
// these states have been split, replaced, or shelved — counting them as
// "open work" drags pillar percentages down for no reason.
const EXCLUDE_FROM_PILLAR_TOTAL = ['superseded', 'deferred', 'cancelled'];

// Status → background colour. The first key that matches (case-insensitive
// substring on the normalised status) wins. Keep specific keys before
// generic ones (e.g. 'partial' before 'done').
const STATUS_COLORS = [
  ['superseded',         '#cfd8dc'],  // grey: replaced/split out
  ['cancelled',          '#cfd8dc'],  // grey
  ['deferred',           '#d7ccc8'],  // taupe
  ['blocked',            '#ef9a9a'],  // hot red
  ['partial',            '#fff3e0'],  // pale orange
  ['phase',              '#fff3e0'],  // pale orange (phase X done…)
  ['pending',            '#ffe0b2'],  // orange
  ['research signed off','#ffe0b2'],  // orange
  ['spec promoted',      '#e1bee7'],  // light purple
  ['spec',               '#e1bee7'],  // light purple
  ['draft',              '#e1bee7'],  // light purple
  ['implemented',        '#fff9c4'],  // yellow
  ['done',               '#c8e6c9'],  // green
  ['complete',           '#c8e6c9'],  // green
  ['open',               '#ffcdd2'],  // red
];

// TEMPLATE v2's closed six-value status vocabulary, applied as EXACT
// matches (whenTextEqualTo) so these take priority over the broader
// whenTextContains rules above and never partial-match e.g. "phase done"
// or "partial done" as plain "done".
const STATUS_COLORS_V2_EXACT = [
  ['done',         '#c8e6c9'],
  ['in-progress',  '#fff9c4'],
  ['open',         '#ffcdd2'],
  ['blocked',      '#ef9a9a'],
  ['paused',       '#e0e0e0'],
  ['superseded',   '#e0e0e0'],
];

const S = {
  dashboard: 'Dashboard',
  prompts  : 'Prompts',          // ← NEW
  packages : 'Packages',
  pillars  : 'Pillars',
  prs      : 'PRs (open)',
  issues   : 'Issues (open)',
  commits  : 'Commits',
  timeline : 'Timeline',
  about    : 'About',
};

// ───────────── Top-level entry points ─────────────

/** Build (or rebuild) every sheet from scratch and pull live data. */
function setup() {
  const ss = getOrCreateSpreadsheet_();
  ensureSheets_(ss);
  buildAbout_(ss);
  buildPillars_(ss);
  refresh_(ss);
  buildDashboard_(ss);
  reorderSheets_(ss);
  installOnOpenMenuTrigger_(ss);
  Logger.log('Setup complete. Open your sheet:');
  Logger.log(ss.getUrl());
}

/** Refresh all live data. Called by setup() and by the daily trigger. */
function refresh() { refresh_(getOrCreateSpreadsheet_()); }
function refresh_(ss) {
  ensureSheets_(ss);
  refreshPackages_(ss);
  refreshPRs_(ss);
  refreshIssues_(ss);
  refreshCommits_(ss);
  refreshTimeline_(ss);
  refreshPrompts_(ss);  
  buildPillars_(ss);     // pillars table is data-only — fine to rebuild
  buildDashboard_(ss);   // rebuild dashboard with current data
  stampAbout_(ss);
}

function installDailyTrigger() {
  removeDailyTrigger();
  ScriptApp.newTrigger('refresh').timeBased().everyDays(1).atHour(7).create();
  Logger.log('Auto-refresh installed: daily at 7am.');
}

function removeDailyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'refresh')
    .forEach(t => ScriptApp.deleteTrigger(t));
}

/** Standalone scripts need an installable onOpen trigger to add a menu. */
function installOnOpenMenuTrigger_(ss) {
  const has = ScriptApp.getProjectTriggers()
    .some(t => t.getHandlerFunction() === 'onOpenMenu');
  if (!has) {
    ScriptApp.newTrigger('onOpenMenu').forSpreadsheet(ss).onOpen().create();
  }
}

function applyConditionalRules_(sh, ranges) {
  const rules = sh.getConditionalFormatRules();
  ranges.forEach(([range, kw, bg]) => {
    rules.push(
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextContains(kw).setBackground(bg).setRanges([range]).build()
    );
  });
  sh.setConditionalFormatRules(rules);
}

/** Build a denominator formula fragment that counts pillar `p` packages
 *  while excluding statuses in EXCLUDE_FROM_PILLAR_TOTAL. */
function pillarDenom_(p) {
  const subs = EXCLUDE_FROM_PILLAR_TOTAL.map(s =>
    `- COUNTIFS('${S.packages}'!C:C, ${p}, '${S.packages}'!D:D, "${s}")`
  ).join(' ');
  return `(COUNTIF('${S.packages}'!C:C, ${p}) ${subs})`;
}

/** Apply the full STATUS_COLORS palette to a status-bearing range. */
function applyStatusColors_(sh, range) {
  const rules = sh.getConditionalFormatRules();
  STATUS_COLORS_V2_EXACT.forEach(([val, bg]) => {
    rules.push(
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextEqualTo(val).setBackground(bg).setRanges([range]).build()
    );
  });
  STATUS_COLORS.forEach(([kw, bg]) => {
    rules.push(
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextContains(kw).setBackground(bg).setRanges([range]).build()
    );
  });
  sh.setConditionalFormatRules(rules);
}

function onOpenMenu(e) {
  // Fires when the bound Sheet is opened.
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

// ───────────── Spreadsheet bootstrap ─────────────

function getOrCreateSpreadsheet_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('SHEET_ID');
  if (id) {
    try { return SpreadsheetApp.openById(id); } catch (e) { /* fall through */ }
  }
  const ss = SpreadsheetApp.create(SHEET_TITLE);
  props.setProperty('SHEET_ID', ss.getId());
  return ss;
}

function ensureSheets_(ss) {
  Object.values(S).forEach(name => {
    if (!ss.getSheetByName(name)) ss.insertSheet(name);
  });
  const def = ss.getSheetByName('Sheet1');
  if (def && Object.values(S).every(n => ss.getSheetByName(n))) {
    ss.deleteSheet(def);
  }
}

function reorderSheets_(ss) {
  const order = [S.dashboard, S.prompts, S.packages, S.pillars, S.prs, S.issues,
               S.commits, S.timeline, S.about];
  order.forEach((name, idx) => {
    const sh = ss.getSheetByName(name);
    if (sh) {
      ss.setActiveSheet(sh);
      ss.moveActiveSheet(idx + 1);
    }
  });
  ss.setActiveSheet(ss.getSheetByName(S.dashboard));
}

// ───────────── Dashboard ─────────────

function buildDashboard_(ss) {
  const sh = ss.getSheetByName(S.dashboard);
  sh.clear();
  sh.clearConditionalFormatRules();

  // ─── Title ───
  sh.getRange('A1').setValue('Astroray Project Tracker')
    .setFontSize(18).setFontWeight('bold');
  sh.getRange('A2').setFormula(
    `="Last refreshed: " & TEXT('${S.about}'!B2, "yyyy-mm-dd hh:mm")`
  ).setFontColor('#666');

  // ─── KPI band (formulas) ───
  const kpis = [
    ['Pillar 1',  `=COUNTIFS('${S.packages}'!C:C, 1, '${S.packages}'!D:D, "done") & "/" & ${pillarDenom_(1)}`],
    ['Pillar 2',  `=COUNTIFS('${S.packages}'!C:C, 2, '${S.packages}'!D:D, "done") & "/" & ${pillarDenom_(2)}`],
    ['Pillar 3',  `=COUNTIFS('${S.packages}'!C:C, 3, '${S.packages}'!D:D, "done") & "/" & ${pillarDenom_(3)}`],
    ['Pillar 4',  `=COUNTIFS('${S.packages}'!C:C, 4, '${S.packages}'!D:D, "done") & "/" & ${pillarDenom_(4)}`],
    ['Pillar 5',  `=COUNTIFS('${S.packages}'!C:C, 5, '${S.packages}'!D:D, "done") & "/" & ${pillarDenom_(5)}`],
    ['Open PRs',     `=COUNTA('${S.prs}'!A2:A)`],
    ['Open issues',  `=COUNTA('${S.issues}'!A2:A)`],
    ['Total packages', `=COUNTA('${S.packages}'!A2:A)`],
  ];
  sh.getRange(4, 1, 1, kpis.length).setValues([kpis.map(k => k[0])])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white').setHorizontalAlignment('center');
  sh.getRange(5, 1, 1, kpis.length).setFormulas([kpis.map(k => k[1])])
    .setFontSize(14).setHorizontalAlignment('center').setBackground('#e8f0fe');
  sh.setRowHeight(5, 36);

  // ─── Strategic gate banner ───
  sh.getRange('A8').setValue('Strategic gate').setFontWeight('bold').setBackground('#fbbc04');
  sh.getRange('B8').setValue(STRATEGIC_GATE).setBackground('#fff8e1').setWrap(true);
  sh.getRange('B8:G8').merge();

  // ─── What's open (direct values + hyperlinks, no QUERY) ───
  sh.getRange('A10').setValue("What's open right now (not done)").setFontWeight('bold');
  sh.getRange(11, 1, 1, 5).setValues([['Package', 'Title', 'Pillar', 'Status', 'Spec']])
    .setFontWeight('bold').setBackground('#e8f0fe');

  const pkgSh = ss.getSheetByName(S.packages);
  const lastPkgRow = pkgSh.getLastRow();
  const openRows = [];
  if (lastPkgRow > 1) {
    const vals = pkgSh.getRange(2, 1, lastPkgRow - 1, 6).getValues();
    const fmls = pkgSh.getRange(2, 1, lastPkgRow - 1, 6).getFormulas();
    // Hide statuses that are not actually "open work": done, replaced,
    // shelved, or not-yet-actionable spec drafts.
    const HIDE_FROM_OPEN = ['done', 'superseded', 'cancelled', 'deferred', 'draft'];
    for (let i = 0; i < vals.length; i++) {
      const st = String(vals[i][3] || '').toLowerCase();
      if (!st) continue;
      if (HIDE_FROM_OPEN.indexOf(st) !== -1) continue;
      openRows.push({
        pkg:    fmls[i][0] || vals[i][0],   // hyperlink formula or text
        title:  vals[i][1],
        pillar: vals[i][2],
        status: vals[i][3],
        path:   vals[i][5],
      });
    }
  }
  openRows.sort((a, b) =>
    (Number(a.pillar) - Number(b.pillar)) ||
    String(a.pkg).localeCompare(String(b.pkg))
  );
  const openLimited = openRows.slice(0, 20);
  if (openLimited.length) {
    const startRow = 12;
    sh.getRange(startRow, 1, openLimited.length, 1).setFormulas(
      openLimited.map(r => [r.pkg && r.pkg.charAt(0) === '=' ? r.pkg : `="${r.pkg}"`])
    );
    sh.getRange(startRow, 2, openLimited.length, 4).setValues(
      openLimited.map(r => [r.title, r.pillar, r.status, r.path])
    );

    // Status colour-coding (full palette).
    const dashStatusRange = sh.getRange(12, 4, openLimited.length, 1);
    applyStatusColors_(sh, dashStatusRange);
  } else {
    sh.getRange(12, 1).setValue('Nothing open. 🎉').setFontStyle('italic').setFontColor('#666');
  }

  // ─── Pillar progress (direct values from Pillars sheet, top section) ───
  sh.getRange('H10').setValue('Pillar progress').setFontWeight('bold');
  const pillarsSh = ss.getSheetByName(S.pillars);
  const pillarVals = pillarsSh.getRange(1, 1, 6, 4).getDisplayValues();
  sh.getRange(11, 8, 6, 4).setValues(pillarVals);
  sh.getRange(11, 8, 1, 4).setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  // ─── Recent commits preview (direct write) ───
  sh.getRange('A33').setValue('Recent commits (last 10)').setFontWeight('bold');
  const commitsSh = ss.getSheetByName(S.commits);
  const cLast = Math.min(commitsSh.getLastRow(), 11);   // 1 header + 10 rows
  if (cLast > 1) {
    const cVals = commitsSh.getRange(1, 1, cLast, 4).getDisplayValues();
    sh.getRange(34, 1, cVals.length, 4).setValues(cVals);
    sh.getRange(34, 1, 1, 4).setFontWeight('bold').setBackground('#e8f0fe');
  }

  // ─── Open PRs preview (direct write) ───
  sh.getRange('H33').setValue('Open PRs').setFontWeight('bold');
  const prsSh = ss.getSheetByName(S.prs);
  const pLast = Math.min(prsSh.getLastRow(), 11);
  if (pLast > 1) {
    const pVals = prsSh.getRange(1, 1, pLast, 5).getDisplayValues();
    sh.getRange(34, 8, pVals.length, 5).setValues(pVals);
    sh.getRange(34, 8, 1, 5).setFontWeight('bold').setBackground('#e8f0fe');
  } else {
    sh.getRange(34, 8).setValue('No open PRs. 🎉').setFontStyle('italic').setFontColor('#666');
  }

  // ─── Layout ───
  sh.setColumnWidth(1, 90);
  sh.setColumnWidth(2, 380);
  sh.setColumnWidth(3, 60);
  sh.setColumnWidth(4, 200);
  sh.setColumnWidth(5, 360);
  sh.setColumnWidth(8, 70);
  sh.setColumnWidth(9, 280);
  sh.setColumnWidth(10, 90);
  sh.setColumnWidth(11, 90);
  sh.setColumnWidth(12, 360);
  sh.setHiddenGridlines(true);
  sh.setFrozenRows(2);
}

// ───────────── Pillars ─────────────

function buildPillars_(ss) {
  const sh = ss.getSheetByName(S.pillars);
  sh.clear();

  // ─── Summary table ───
  const header = ['Pillar', 'Name', 'Done', '%'];
  const pillars = [
    [1, 'Plugin architecture'],
    [2, 'Spectral core'],
    [3, 'Light transport'],
    [4, 'Astrophysics platform'],
    [5, 'Production polish / Blender parity'],
  ];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');
  sh.getRange(2, 1, pillars.length, 2).setValues(pillars);
  for (let i = 0; i < pillars.length; i++) {
    const p = pillars[i][0], r = i + 2;
    sh.getRange(r, 3).setFormula(
      `=COUNTIFS('${S.packages}'!C:C, ${p}, '${S.packages}'!D:D, "done") & "/" & ${pillarDenom_(p)}`
    );
    sh.getRange(r, 4).setFormula(
      `=IFERROR(COUNTIFS('${S.packages}'!C:C, ${p}, '${S.packages}'!D:D, "done")/${pillarDenom_(p)}, 0)`
    ).setNumberFormat('0%');
  }

  // ─── Per-pillar drill-down sections ───
  let row = pillars.length + 4;     // gap after the summary
  pillars.forEach(([p, name]) => {
    // Section header
    sh.getRange(row, 1).setFormula(
      `="Pillar ${p} — ${name}  ("&COUNTIFS('${S.packages}'!C:C,${p},'${S.packages}'!D:D,"done")&"/"&COUNTIF('${S.packages}'!C:C,${p})&" done)"`
    ).setFontWeight('bold').setFontSize(12).setBackground('#1a73e8').setFontColor('white');
    sh.getRange(row, 1, 1, 5).merge();
    row++;
    // Sub-header
    sh.getRange(row, 1, 1, 5).setValues([['Package', 'Title', 'Status', 'Effort', 'Spec']])
      .setFontWeight('bold').setBackground('#e8f0fe');
    row++;
    // Body — one QUERY per pillar, sorted: not-done first (so blockers float up)
    sh.getRange(row, 1).setFormula(
      `=QUERY('${S.packages}'!A:F, ` +
      `"select A,B,D,E,F where C=${p} order by D desc, A asc", 1)`
    );
    // Reserve a chunk of rows for conditional formatting + spacing
    const slotRows = 28;            // big enough for any pillar
    row += slotRows + 1;            // +1 blank line gap
  });

  // ─── Conditional formatting on the % column ───
  const pctRange = sh.getRange(2, 4, pillars.length, 1);
  const rules = [];
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .setGradientMaxpointWithValue('#34a853', SpreadsheetApp.InterpolationType.NUMBER, '1')
      .setGradientMidpointWithValue('#fbbc04', SpreadsheetApp.InterpolationType.NUMBER, '0.5')
      .setGradientMinpointWithValue('#ea4335', SpreadsheetApp.InterpolationType.NUMBER, '0')
      .setRanges([pctRange]).build()
  );

  // Status colours across every pillar drill-down section.
  const drilldownRange = sh.getRange('C9:C200');
  STATUS_COLORS_V2_EXACT.forEach(([val, bg]) => {
    rules.push(
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextEqualTo(val).setBackground(bg).setRanges([drilldownRange]).build()
    );
  });
  STATUS_COLORS.forEach(([kw, bg]) => {
    rules.push(
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextContains(kw).setBackground(bg).setRanges([drilldownRange]).build()
    );
  });

  sh.setConditionalFormatRules(rules);
  sh.setColumnWidths(1, 1, 80);
  sh.setColumnWidths(2, 1, 380);
  sh.setColumnWidths(3, 1, 280);
  sh.setColumnWidths(4, 1, 160);
  sh.setColumnWidths(5, 1, 280);
  sh.setFrozenRows(1);
  sh.setHiddenGridlines(true);
}

// ───────────── Packages ─────────────

function refreshPackages_(ss) {
  const sh = ss.getSheetByName(S.packages);
  sh.clear();
  const header = ['Package', 'Title', 'Pillar', 'Status', 'Effort', 'Path'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

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

  const statusRange = sh.getRange(2, 4, Math.max(1, rows.length), 1);
  applyStatusColors_(sh, statusRange);

  sh.setColumnWidths(1, 1, 80);
  sh.setColumnWidths(2, 1, 380);
  sh.setColumnWidths(3, 1, 70);
  sh.setColumnWidths(4, 1, 280);
  sh.setColumnWidths(5, 1, 160);
  sh.setColumnWidths(6, 1, 380);
  sh.setFrozenRows(1);
  if (sh.getFilter()) sh.getFilter().remove();
  sh.getDataRange().createFilter();
}

/**
 * parsePackageMd_ / status normalisation -- worked examples.
 * (No Apps Script test runner exists; this documents the contract by hand.)
 *
 * 1. "**Pillar:** 2\n**Status:** done — PR #716, 2026-09-06"
 *      -> pillar: 2, status: "done"              (TEMPLATE v2 exact form)
 * 2. "**Pillar:** 2 (BSDF energy conservation...)\n**Status:** LANDED (#686, 2026-09-04)"
 *      -> pillar: 2, status: "done"              (legacy leading-digit Pillar
 *                                                  + legacy "landed" -> done)
 * 3. "**Pillar:**\n**Status:** in-progress — Stage 2 of 3"
 *      -> pillar: '', status: "in-progress"      (v2 exact-vocabulary branch)
 */
function parsePackageMd_(md) {
  const lines = md.split(/\r?\n/).slice(0, 120);
  const meta = { title: '', pillar: '', status: '', effort: '' };

  // Collect lines first so we can fold multi-line **Field:** values.
  // A continuation line is one that starts with whitespace and isn't
  // itself a new field (i.e. not `**Foo:**`).
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trim();

    if (!meta.title && /^#\s+/.test(line)) {
      meta.title = line
        .replace(/^#\s+/, '')
        .replace(/^pkg[0-9a-z-]+\s*[—\-:]\s*/i, '')
        .replace(/\s+[—\-]\s+(SPEC|DRAFT|WIP)\s*$/i, '')   // strip trailing " — SPEC"
        .replace(/\s*\((SPEC|DRAFT|WIP)\)\s*$/i, '')        // strip trailing "(SPEC)"
        .trim();
      continue;
    }

    const fieldMatch = line.match(/^\*\*(Pillar|Status|Estimated effort):\*\*\s*(.*)$/i);
    if (fieldMatch) {
      const field = fieldMatch[1].toLowerCase();
      let value = fieldMatch[2];
      // Fold continuation lines (indented and not a new **Field:** line).
      while (i + 1 < lines.length) {
        const next = lines[i + 1];
        if (next === '' || !/^\s/.test(next)) break;
        if (/^\s*\*\*[A-Za-z][^*]*:\*\*/.test(next)) break;
        value += ' ' + next.trim();
        i++;
      }
      value = stripMd_(value).trim();
      if (field === 'pillar' && !meta.pillar) {
        // TEMPLATE v2: Pillar is a bare integer 1-5, or empty for
        // infrastructure -- never fall back to raw prose text. Try the
        // strict v2 shape first, then a legacy leading-digit shape.
        if (/^([1-5])$/.test(value)) {
          meta.pillar = Number(value);
        } else {
          const lead = value.match(/^([1-5])\b/);
          meta.pillar = lead ? Number(lead[1]) : '';
        }
      } else if (field === 'status' && !meta.status) {
        meta.status = value;
      } else if (field === 'estimated effort' && !meta.effort) {
        meta.effort = value;
      }
    }
  }

  // Normalise the status into a small, colour-friendly vocabulary.
  const s = meta.status.toLowerCase();
  // TEMPLATE v2: try the closed six-value vocabulary first (a bare token,
  // or a token followed by " — <free text>"). Falls through to the legacy
  // heuristic chain below for the pre-v2 corpus.
  const v2 = s.match(/^(open|in-progress|blocked|paused|done|superseded)(?:\s+—|$)/);
  if (v2)                                                          meta.status = v2[1];
  else if (/^superseded\b/.test(s))                                meta.status = 'superseded';
  else if (/^cancelled\b/.test(s))                                 meta.status = 'cancelled';
  else if (/^deferred\b/.test(s))                                  meta.status = 'deferred';
  else if (/^blocked\b/.test(s))                                   meta.status = 'blocked';
  else if (/^partial[_\s-]?done\b/.test(s) || /^partial\b/.test(s)) meta.status = 'partial done';
  else if (/^phase\b/.test(s) && /\bdone\b/.test(s) && /(remain|defer|await|pending|not\s+yet|blocked)/.test(s))
                                                                   meta.status = 'phase partial';
  else if (/^phase\b/.test(s) && /\bdone\b/.test(s))               meta.status = 'phase done';
  else if (/(^|[^a-z])done([^a-z]|$)/.test(s) && /(pending|await|defer|remain|not\s+yet)/.test(s))
                                                                   meta.status = 'partial done';
  else if (/(^|[^a-z])done([^a-z]|$)/.test(s) || /^complete\b/.test(s) || /^landed\b/.test(s))
                                                                   meta.status = 'done';
  else if (/^implemented\b/.test(s))                               meta.status = 'done';
  else if (/research/.test(s) && /(blocked|signed off|signed-off|signoff|sign\-off)/.test(s))
                                                                   meta.status = 'research signed off';
  else if (/^spec promoted\b/.test(s) || /^spec\b/.test(s))        meta.status = 'spec promoted';
  else if (/^draft\b/.test(s))                                     meta.status = 'draft';
  else if (/^pending\b/.test(s))                                   meta.status = 'pending';
  else if (/^(proposed|approved)\b/.test(s))                       meta.status = 'open';
  else if (/^in\s+flight\b/.test(s))                                meta.status = 'in-progress';
  else if (/^open\b/.test(s))                                      meta.status = 'open';
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
  if (sh.getFilter()) sh.getFilter().remove();
  sh.getDataRange().createFilter();
    // Grey-tint draft PRs, green-tint others (column E = mergeable)
  const stateRange = sh.getRange('E2:E' + Math.max(2, rows.length + 1));
  applyConditionalRules_(sh, [
    [stateRange, 'draft', '#eceff1'],
    [stateRange, 'open',  '#c8e6c9'],
  ]);
}


function refreshPrompts_(ss) {
  const sh = ss.getSheetByName(S.prompts);
  sh.clear();
  sh.clearConditionalFormatRules();
  const header = ['#', 'Agent', 'Worktree / location', 'Title', 'Prompt'];
  sh.getRange(1, 1, 1, header.length).setValues([header])
    .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

  const md = httpGet_(rawUrl_('.astroray_plan/docs/NEXT_STAGE_REPORT.md'));
  if (!md) {
    sh.getRange('A2').setValue('Error fetching NEXT_STAGE_REPORT.md');
    return;
  }

  // Parse §3 sections: ### 3.X <agent>(<location>) — <title>\n\n```\n<prompt>\n```
  // The "(<location>)" part is optional.
  const re = /^###\s+(3\.\d+)\s+(.+?)\s+—\s+(.+?)\n+```[a-z]*\n([\s\S]+?)\n```/gm;
  const rows = [];
  let m;
  while ((m = re.exec(md))) {
    const num   = m[1];
    let agent   = m[2].trim();
    let where   = '';
    const wm = agent.match(/^(.+?)\s*\((.+?)\)\s*$/);
    if (wm) { agent = wm[1].trim(); where = wm[2].trim(); }
    rows.push([num, agent, where, m[3].trim(), m[4].trim()]);
  }
  rows.sort((a, b) => {
    const na = a[0].split('.').map(Number);
    const nb = b[0].split('.').map(Number);
    return (na[0] - nb[0]) || (na[1] - nb[1]);
  });

  if (rows.length) {
    sh.getRange(2, 1, rows.length, header.length).setValues(rows);
    // Wrap the prompt column, monospace it, top-align everything
    sh.getRange(2, 5, rows.length, 1).setWrap(true).setFontFamily('Roboto Mono').setFontSize(10);
    sh.getRange(2, 1, rows.length, header.length).setVerticalAlignment('top');
    // Generous row heights so prompts are readable without expanding
    sh.setRowHeights(2, rows.length, 240);

    // Tint by agent (column B)
    const agentRange = sh.getRange(2, 2, rows.length, 1);
    const rules = sh.getConditionalFormatRules();
    const tint = (kw, bg) =>
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextContains(kw).setBackground(bg).setRanges([agentRange]).build();
    rules.push(tint('CUDA verifier', '#bbdefb'));   // blue: hardware
    rules.push(tint('Claude tech',   '#fff9c4'));   // yellow: Claude
    sh.setConditionalFormatRules(rules);
  } else {
    sh.getRange(2, 1).setValue('No drop-in prompts parsed (§3 not found in NEXT_STAGE_REPORT.md).')
      .setFontStyle('italic').setFontColor('#666');
  }

  sh.setColumnWidths(1, 1, 50);
  sh.setColumnWidths(2, 1, 150);
  sh.setColumnWidths(3, 1, 240);
  sh.setColumnWidths(4, 1, 320);
  sh.setColumnWidths(5, 1, 720);
  sh.setFrozenRows(1);
  sh.setHiddenGridlines(true);
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
  if (sh.getFilter()) sh.getFilter().remove();
  sh.getDataRange().createFilter();
    // Tint labels (column C)
  const labelRange = sh.getRange('C2:C' + Math.max(2, rows.length + 1));
  applyConditionalRules_(sh, [
    [labelRange, 'bug',         '#ffcdd2'],   // red: bugs
    [labelRange, 'P1-high',     '#ffe0b2'],   // orange: P1
    [labelRange, 'P0',          '#ef9a9a'],   // hot red: P0
    [labelRange, 'enhancement', '#c8e6c9'],   // green: enhancements
    [labelRange, 'P2-medium',   '#fff9c4'],   // yellow: P2
    [labelRange, 'P3-low',      '#eceff1'],   // grey: P3
  ]);
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
  // SHA column: force plain text so SHAs that happen to look numeric
  // (e.g. all-digit short hashes like 3414095) don't get coerced into
  // scientific notation by Sheets' default formatting.
  sh.getRange(2, 1, Math.max(1, rows.length), 1).setNumberFormat('@');
  sh.getRange(2, 4, Math.max(1, rows.length), 1).setNumberFormat('yyyy-mm-dd hh:mm');
  sh.setColumnWidths(1, 1, 90);
  sh.setColumnWidths(2, 1, 560);
  sh.setColumnWidths(3, 1, 160);
  sh.setColumnWidths(4, 1, 150);
  sh.setFrozenRows(1);
  if (sh.getFilter()) sh.getFilter().remove();
  sh.getDataRange().createFilter();
    // Tint by commit type (column B = message)
  const msgRange = sh.getRange('B2:B' + Math.max(2, rows.length + 1));
  applyConditionalRules_(sh, [
    [msgRange, 'feat(',   '#c8e6c9'],   // green: features
    [msgRange, 'fix(',    '#ffe0b2'],   // orange: fixes
    [msgRange, 'verify(', '#bbdefb'],   // blue: verification
    [msgRange, 'diag(',   '#e1bee7'],   // purple: diagnostics
    [msgRange, 'docs',    '#eceff1'],   // grey: docs
  ]);
}

// ───────────── Timeline ─────────────

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

  const entries = [];
  const re = /(?:^|\n)\*\*(\d{4}-\d{2}-\d{2})([\s\S]*?)(?=\n\*\*\d{4}-\d{2}-\d{2}|\n## |$)/g;
  let m;
  while ((m = re.exec(tail))) {
    const date = m[1];
    const summary = m[2].replace(/\s+/g, ' ').trim();
    entries.push([new Date(date), summary.length > 600 ? summary.slice(0, 600) + '…' : summary]);
  }
  entries.sort((a, b) => b[0] - a[0]);
  if (entries.length) sh.getRange(2, 1, entries.length, 2).setValues(entries);
  sh.getRange(2, 1, Math.max(1, entries.length), 1).setNumberFormat('yyyy-mm-dd');
  sh.setColumnWidths(1, 1, 110);
  sh.setColumnWidths(2, 1, 900);
  sh.setFrozenRows(1);
  if (sh.getFilter()) sh.getFilter().remove();
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
    ['How to refresh', 'Astroray menu → Refresh now (after first reload), or run installDailyTrigger() once for auto-refresh.'],
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