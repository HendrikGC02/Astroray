"""pkg119 Phase C - graceful-degradation policy (translation-honesty layer).

The addon must NEVER render silently-wrong. Every unsupported or approximated
Blender input is EITHER approximated-with-warning OR explicitly reported-ignored,
surfaced ONCE per render in the addon UI and the logs. This module is the single
POLICY the addon's previously-parallel warning sources funnel through:

  1. shader-node fallbacks (``CustomRaytracerRenderEngine._warn_shader_fallback``,
     seeded by pkg115) - recorded as APPROXIMATED;
  2. native world/light/camera drops (pkg176 Stage 3
     ``native_settings.report_unsupported_native_controls``) - recorded as IGNORED;
  3. DROPPED-SILENT translation-dispatch fall-throughs (an unsupported surface
     shader node routed to a neutral grey material) surfaced at the dispatch
     site - recorded as IGNORED.

Route-2 discipline (dcc-integration-decision-2026-08 s6): this is a pure
collector/formatter. It holds NO bpy or engine/session references; the render
engine hands it a Blender ``report`` callback only at :meth:`emit` time. This
keeps it standalone-loadable and unit-testable without Blender.
"""

from __future__ import annotations


class DegradationReport:
    """Per-render accumulator of translation degradations.

    Two dispositions, both surfaced (never silent):

      * :meth:`approximate` - a recognised input mapped to a nearest engine
        behaviour (e.g. Cycles microfiber sheen -> Disney sheen).
      * :meth:`ignore` - an input the engine cannot honour yet and drops (e.g.
        an unsupported surface shader node, an ORTHO camera).

    Entries are de-duplicated (a feature warns once per render) and preserve
    insertion order for a stable, readable consolidated report.
    """

    def __init__(self):
        self._approximated = []   # list of (feature, detail)
        self._ignored = []        # list of (feature, detail)
        self._seen = set()        # dedup keys across both buckets

    def _record(self, bucket, tag, feature, detail):
        key = (tag, feature, detail)
        if key in self._seen:
            return
        self._seen.add(key)
        bucket.append((feature, detail))

    def approximate(self, feature, detail=""):
        """Record a recognised-but-approximated input."""
        self._record(self._approximated, "approx", str(feature), str(detail))

    def ignore(self, feature, detail=""):
        """Record an unsupported input that is dropped (reported, not silent)."""
        self._record(self._ignored, "ignore", str(feature), str(detail))

    def ignore_messages(self, messages):
        """Fold a list of pre-formatted human-readable drop messages (e.g. the
        return value of ``report_unsupported_native_controls``) into the ignored
        bucket."""
        for msg in messages or []:
            self.ignore(str(msg))

    @property
    def approximated(self):
        return list(self._approximated)

    @property
    def ignored(self):
        return list(self._ignored)

    def is_empty(self):
        return not self._approximated and not self._ignored

    @staticmethod
    def _line(feature, detail):
        return f"{feature}: {detail}" if detail else feature

    def messages(self):
        """Per-disposition human-readable lines, approximated first."""
        lines = []
        for feature, detail in self._approximated:
            lines.append("approximated " + self._line(feature, detail))
        for feature, detail in self._ignored:
            lines.append("ignored " + self._line(feature, detail))
        return lines

    def summary(self):
        return (
            f"Astroray degradation: {len(self._approximated)} approximated / "
            f"{len(self._ignored)} ignored"
        )

    def text(self):
        """The full consolidated report line, or "" when nothing degraded."""
        if self.is_empty():
            return ""
        return self.summary() + " -- " + "; ".join(self.messages())

    def emit(self, report=None):
        """Surface the consolidated report ONCE. Uses the Blender ``report``
        callback when given (a ``WARNING`` so it lands in the addon UI /
        info log) and always mirrors to stdout. No-op when nothing degraded.

        Returns the consolidated text ("" when empty) for tests / callers that
        want to log it differently."""
        text = self.text()
        if not text:
            return ""
        if report is not None:
            try:
                report({'WARNING'}, text)
            except (TypeError, RuntimeError):
                print(text)
                return text
        print(text)
        return text
