// guide_context.h — the record the CPU path tracer emits for SD-tree training.
//
// A path-guiding radiance record: at a shading point `p`, the continuation
// direction `w` (world space) carried scalar incident radiance `value`
// (luminance of the downstream contribution / throughput at that vertex). During
// a training pass, pathTraceSpectral appends these to a per-thread buffer; a
// single-threaded pass between iterations replays them into the building SDTree
// (see .astroray_plan/docs/pkg136-stage1b-design.md — deferred-splat threading).
//
// License: Apache-2.0

#pragma once

namespace astroray {
namespace guiding {

struct GuideRecord {
    float p[3];
    float w[3];
    float value;
};

}  // namespace guiding
}  // namespace astroray
