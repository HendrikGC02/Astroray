#pragma once
// light_tree_device.cuh — device-side light tree traversal (pkg86-B Phase 2).
//
// 1:1 CUDA mirror of the CPU implementation in src/light_tree.cpp
// (importance / pick / pdf), which itself mirrors Blender Cycles
// kernel/light/tree.h::light_tree_importance + light_tree_sample
// (Apache-2.0, commit e52e5eb06f6b24055f0e7508bc7d7278e139ba0f, vendored at
// external/cycles_light_tree/). Algorithm: Conty & Kulla 2018,
// "Importance Sampling of Many Lights with Adaptive Tree Splitting",
// DOI 10.1145/3233305.
//
// The traversal is an iterative stochastic descent (no recursion, no stack) —
// the same control flow Cycles uses on the GPU. The pdf walk follows a
// host-precomputed per-emitter bit trail (root->leaf path) instead of the
// CPU's recursive subtreeContainsEmitter, mirroring Cycles' bit_trail.
// Only include this from .cu files compiled by nvcc.

#include "astroray/gpu_types.h"

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif

// Mirror of LightTree::importanceMinMax (src/light_tree.cpp; Cycles
// light_tree_importance, kernel/light/tree.h). Keep the float math IDENTICAL
// to the CPU reference — the pkg86-B parity gate compares pick decisions.
__device__ inline void gpu_light_tree_importance_mm(
    const GVec3& bboxMin, const GVec3& bboxMax, const GVec3& bconeAxis,
    float thetaO, float thetaE, float energy,
    const GVec3& point, const GVec3& normal, float* maxImp, float* minImp)
{
    *maxImp = 0.0f;
    *minImp = 0.0f;
    GVec3 centroid = (bboxMin + bboxMax) * 0.5f;
    float bboxRadius = (bboxMax - centroid).length();
    GVec3 pointToCentroidNorm;
    float cosSubtendedAngle;
    float clampedDistance;
    if (!(bboxRadius < 1e9f)) {
        // #851: distant node/emitter (Cycles LIGHT_TREE_DISTANT), CPU mirror.
        pointToCentroidNorm = (bconeAxis * -1.0f).normalized();
        cosSubtendedAngle = cosf(fminf(M_PI_F, thetaO + thetaE));
        clampedDistance = 1.0f;
    } else {
        GVec3 pointToCentroid = centroid - point;
        float distance = pointToCentroid.length();
        if (distance < 1e-6f) distance = 1e-6f;
        pointToCentroidNorm = pointToCentroid / distance;
        float distanceSq = distance * distance;
        float radiusSq = bboxRadius * bboxRadius;
        if (distanceSq <= radiusSq) {
            cosSubtendedAngle = -1.0f;  // point inside bounding sphere
        } else {
            float sinSubtendedAngleSq = radiusSq / distanceSq;
            cosSubtendedAngle = sqrtf(1.0f - sinSubtendedAngleSq);
        }
        // #851: Cycles distance clamp (light_tree_node_importance), see CPU mirror.
        clampedDistance = fmaxf(0.5f * bboxRadius, distance);
    }
    float sinSubtendedAngle = sqrtf(fmaxf(0.0f, 1.0f - cosSubtendedAngle * cosSubtendedAngle));

    // Zero normal = volume vertex (no incidence term); surfaces use
    // has_transmission (|cos|, no prune). Mirror of the CPU (#851 review C2).
    float cosMinIncidenceAngle = 1.0f;
    float cosMaxIncidenceAngle = 1.0f;
    if (normal.dot(normal) > 0.0f) {
        float cosThetaI = fabsf(pointToCentroidNorm.dot(normal));
        float sinThetaI = sqrtf(fmaxf(0.0f, 1.0f - cosThetaI * cosThetaI));
        if (cosThetaI >= cosSubtendedAngle) {
            cosMinIncidenceAngle = 1.0f;
        } else {
            cosMinIncidenceAngle = cosThetaI * cosSubtendedAngle + sinThetaI * sinSubtendedAngle;
        }
        cosMaxIncidenceAngle =
            fmaxf(cosThetaI * cosSubtendedAngle - sinThetaI * sinSubtendedAngle, 0.0f);
    }

    // Angle between cluster axis and emission direction toward the point.
    GVec3 negPointToCentroid = pointToCentroidNorm * -1.0f;
    float cosTheta = bconeAxis.dot(negPointToCentroid);
    float sinTheta = sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta));

    float cosThetaMinusSubtended = cosTheta * cosSubtendedAngle + sinTheta * sinSubtendedAngle;

    // Cone-cone visibility test (cos_min_outgoing_angle).
    float cosThetaO = cosf(thetaO);
    float sinThetaO = sinf(thetaO);

    float cosMinOutgoingAngle;
    if (cosTheta >= cosSubtendedAngle || cosThetaMinusSubtended >= cosThetaO) {
        cosMinOutgoingAngle = 1.0f;
    } else if ((thetaO + thetaE > M_PI_F) ||
               (cosThetaMinusSubtended > cosf(thetaO + thetaE))) {
        float sinThetaMinusSubtended = sqrtf(fmaxf(0.0f, 1.0f - cosThetaMinusSubtended * cosThetaMinusSubtended));
        cosMinOutgoingAngle = cosThetaMinusSubtended * cosThetaO + sinThetaMinusSubtended * sinThetaO;
    } else {
        return;  // cluster invisible from this shading point
    }

    *maxImp = energy * cosMinIncidenceAngle * cosMinOutgoingAngle /
              (clampedDistance * clampedDistance);

    // Lower bound (Cycles tree.h), used only for leaf emitter selection.
    float cosThetaPlusSubtended = cosTheta * cosSubtendedAngle - sinTheta * sinSubtendedAngle;
    if (thetaE - thetaO < 0.0f || cosTheta < 0.0f || cosSubtendedAngle < 0.0f ||
        cosThetaPlusSubtended < cosf(thetaE - thetaO)) {
        *minImp = 0.0f;
    } else {
        float sinThetaPlusSubtended =
            sqrtf(fmaxf(0.0f, 1.0f - cosThetaPlusSubtended * cosThetaPlusSubtended));
        float cosMaxOutgoingAngle = cosThetaPlusSubtended * cosThetaO - sinThetaPlusSubtended * sinThetaO;
        *minImp = fabsf(energy * cosMaxIncidenceAngle * cosMaxOutgoingAngle /
                        (clampedDistance * clampedDistance));
    }
}

__device__ inline float gpu_light_tree_importance(
    const GLightTreeNode& node, const GVec3& point, const GVec3& normal)
{
    float mx, mn;
    gpu_light_tree_importance_mm(node.bboxMin, node.bboxMax, node.bconeAxis,
                                 node.thetaO, node.thetaE, node.energy,
                                 point, normal, &mx, &mn);
    return mx;
}

// Mirror of LightTree::sampleReservoir (Cycles sample_reservoir).
__device__ inline void gpu_light_tree_reservoir(int index, float weight, int* selected,
                                                float* selectedWeight, float* totalWeight,
                                                float* rand)
{
    if (!(weight > 0.0f)) return;
    *totalWeight += weight;
    if (*selected == -1) { *selected = index; *selectedWeight = weight; return; }
    const float thresh = weight / *totalWeight;
    if (*rand <= thresh) {
        *selected = index; *selectedWeight = weight; *rand = *rand / thresh;
    } else {
        *rand = (*rand - thresh) / (1.0f - thresh);
    }
    *rand = fminf(fmaxf(*rand, 0.0f), 1.0f);
}

// Mirror of LightTree::leafEmitterProb (#851; Cycles light_tree_pdf leaf):
// 0.5 * (max_i/sum(max) + min_i/sum(min)), min term uniform over max>0 emitters
// when sum(min) == 0; 0 when no emitter has importance.
__device__ inline float gpu_light_tree_leaf_prob(
    const GLightTreeView& view, const GLightTreeNode& leaf, int target,
    const GVec3& point, const GVec3& normal)
{
    float sumMax = 0.0f, sumMin = 0.0f, tMax = 0.0f, tMin = 0.0f;
    int numHas = 0;
    for (int i = leaf.firstEmitter; i < leaf.firstEmitter + leaf.numEmitters; ++i) {
        const GLightTreeEmitter& e = view.emitters[i];
        float mx, mn;
        gpu_light_tree_importance_mm(e.bboxMin, e.bboxMax, e.bconeAxis,
                                     e.thetaO, e.thetaE, e.energy,
                                     point, normal, &mx, &mn);
        sumMax += mx;
        sumMin += mn;
        numHas += (mx > 0.0f) ? 1 : 0;
        if (i == target) { tMax = mx; tMin = mn; }
    }
    if (!(sumMax > 0.0f) || !(tMax > 0.0f)) return 0.0f;
    float minTerm = sumMin > 0.0f ? tMin / sumMin : 1.0f / (float)numHas;
    return 0.5f * (tMax / sumMax + minTerm);
}

// Mirror of LightTree::pick (src/light_tree.cpp:476-522; Cycles
// light_tree_sample). Returns the emitter index, or -1 when the tree is
// empty. *outPdf receives the discrete selection pdf.
__device__ inline int gpu_light_tree_pick(
    const GLightTreeView& view, const GVec3& point, const GVec3& normal,
    float u, float* outPdf)
{
    if (!view.enabled || view.numNodes == 0) { *outPdf = 0.f; return -1; }

    int nodeIdx = 0;
    float pdf = 1.0f;

    while (!(view.nodes[nodeIdx].firstEmitter >= 0)) {  // isLeaf()
        const GLightTreeNode& node  = view.nodes[nodeIdx];
        const GLightTreeNode& left  = view.nodes[node.leftChild];
        const GLightTreeNode& right = view.nodes[node.rightChild];

        float leftImp  = gpu_light_tree_importance(left, point, normal);
        float rightImp = gpu_light_tree_importance(right, point, normal);
        float totalImp = leftImp + rightImp;

        if (!(totalImp > 0.0f)) {  // #961 review: no light (CPU pickWith, Cycles)
            *outPdf = 0.f;
            return -1;
        } else {
            float leftProb = leftImp / totalImp;
            if (u < leftProb) {
                nodeIdx = node.leftChild;
                pdf *= leftProb;
                u = u / leftProb;
            } else {
                nodeIdx = node.rightChild;
                pdf *= (1.0f - leftProb);
                u = (u - leftProb) / (1.0f - leftProb);
            }
        }
    }

    // #851: one-pass two-reservoir leaf pick (mirror of CPU pick(); Cycles
    // light_tree_cluster_select_emitter).
    // Scalars, not runtime-indexed arrays, so nothing lands in local memory
    // (the shade kernels are register-saturated).
    const GLightTreeNode& leaf = view.nodes[nodeIdx];
    int emitterIdx = -1;
    float selMax = 0.0f, selMin = 0.0f, totMax = 0.0f, totMin = 0.0f;
    int numHas = 0;
    const bool sampleMax = (u > 0.5f);
    if (leaf.numEmitters > 1) u = u * 2.0f - (sampleMax ? 1.0f : 0.0f);
    for (int i = leaf.firstEmitter; i < leaf.firstEmitter + leaf.numEmitters; ++i) {
        const GLightTreeEmitter& e = view.emitters[i];
        float mx, mn;
        gpu_light_tree_importance_mm(e.bboxMin, e.bboxMax, e.bconeAxis,
                                     e.thetaO, e.thetaE, e.energy,
                                     point, normal, &mx, &mn);
        if (sampleMax) {
            gpu_light_tree_reservoir(i, mx, &emitterIdx, &selMax, &totMax, &u);
            if (emitterIdx == i) selMin = mn;
            totMin += mn;
        } else {
            gpu_light_tree_reservoir(i, mn, &emitterIdx, &selMin, &totMin, &u);
            if (emitterIdx == i) selMax = mx;
            totMax += mx;
        }
        numHas += (mx > 0.0f) ? 1 : 0;
    }
    if (numHas == 0) { *outPdf = 0.f; return -1; }
    if (totMin == 0.0f) {
        if (!sampleMax) {
            emitterIdx = -1;
            float w = 0.0f, t = 0.0f;
            for (int i = leaf.firstEmitter; i < leaf.firstEmitter + leaf.numEmitters; ++i) {
                const GLightTreeEmitter& e = view.emitters[i];
                float mx, mn;
                gpu_light_tree_importance_mm(e.bboxMin, e.bboxMax, e.bconeAxis,
                                             e.thetaO, e.thetaE, e.energy,
                                             point, normal, &mx, &mn);
                gpu_light_tree_reservoir(i, mx > 0.0f ? 1.0f : 0.0f, &emitterIdx, &w, &t, &u);
                if (emitterIdx == i) selMax = mx;
            }
        }
        selMin = 1.0f;
        totMin = (float)numHas;
    }

    *outPdf = pdf * 0.5f * (selMax / totMax + selMin / totMin);
    return emitterIdx;
}

// Mirror of LightTree::pdf (src/light_tree.cpp:546-605) with the recursive
// contains-test replaced by the emitter's precomputed bit trail (computed on
// the host in scene_upload.cu; same idea as Cycles' bit_trail in
// kernel/light/tree.h). Walks root->leaf re-deriving the branch
// probabilities the pick traversal would use.
__device__ inline float gpu_light_tree_pdf(
    const GLightTreeView& view, const GVec3& point, const GVec3& normal,
    int emitterIdx)
{
    if (!view.enabled || view.numNodes == 0 || emitterIdx < 0) return 0.f;

    unsigned int trail = view.emitters[emitterIdx].bitTrail;
    float pdf = 1.0f;
    int nodeIdx = 0;

    while (!(view.nodes[nodeIdx].firstEmitter >= 0)) {  // isLeaf()
        const GLightTreeNode& node  = view.nodes[nodeIdx];
        const GLightTreeNode& left  = view.nodes[node.leftChild];
        const GLightTreeNode& right = view.nodes[node.rightChild];

        float leftImp  = gpu_light_tree_importance(left, point, normal);
        float rightImp = gpu_light_tree_importance(right, point, normal);
        float totalImp = leftImp + rightImp;

        bool goLeft = (trail & 1u) == 0u;
        trail >>= 1;

        if (!(totalImp > 0.0f)) return 0.f;  // #961 review: the pick fails here
        {
            float leftProb = leftImp / totalImp;
            pdf *= goLeft ? leftProb : (1.0f - leftProb);
        }
        nodeIdx = goLeft ? node.leftChild : node.rightChild;
    }

    return pdf * gpu_light_tree_leaf_prob(view, view.nodes[nodeIdx], emitterIdx, point, normal);
}

// ---------------------------------------------------------------------------
// #961: segment (in_volume_segment) importance / pick / pdf. Device mirror of
// LightTree::importanceMinMaxSegment / pickSegment / pdfSegment
// (src/light_tree.cpp; Cycles light_tree_node_importance<true> /
// light_tree_sample<true> / light_tree_pdf<true>, kernel/light/tree.h,
// Apache-2.0). Separate functions so the point traversal the shade kernels
// inline above stays untouched; only the intersect stage (segment direct
// light, lamp/emitter-hit MIS after a medium scatter) calls these.
// ---------------------------------------------------------------------------
__device__ inline float gpu_light_tree_importance_seg(
    const GVec3& bboxMin, const GVec3& bboxMax, const GVec3& bconeAxis,
    float thetaO, float thetaE, float energy,
    const GVec3& o, const GVec3& d, float t)
{
    const bool open = !(t < 1e18f);
    GVec3 centroid = (bboxMin + bboxMax) * 0.5f;
    float bboxRadius = (bboxMax - centroid).length();
    GVec3 pointToCentroidNorm;
    float cosSubtendedAngle, clampedDistance, thetaD;
    if (!(bboxRadius < 1e9f)) {
        pointToCentroidNorm = (bconeAxis * -1.0f).normalized();
        cosSubtendedAngle = cosf(fminf(M_PI_F, thetaO + thetaE));
        clampedDistance = 1.0f;
        thetaD = open ? 1.0f : t;
    } else {
        const float closestT = (centroid - o).dot(d);
        const GVec3 closestPoint = o + d * fminf(fmaxf(closestT, 0.0f), open ? 1e30f : t);
        const float distance = (centroid - o - d * closestT).length();
        if (open) {
            thetaD = atan2f(closestT, distance) + 0.5f * M_PI_F;
        } else {
            const float sd = distance > 0.0f ? (t - closestT) / distance : 0.0f;
            thetaD = atan2f(t, distance - closestT * sd);
        }
        // compute_v (Cycles kernel/light/tree.h).
        const GVec3 v0u = o - centroid;
        const GVec3 v1u = v0u + d * fminf(t, 1e12f);
        const float l0 = v0u.length(), l1 = v1u.length();
        GVec3 v;
        if (!(l0 > 0.0f) || !(l1 > 0.0f)) {
            v = (l0 > 0.0f) ? v0u / l0 : (l1 > 0.0f ? v1u / l1 : bconeAxis * -1.0f);
        } else {
            const GVec3 v0 = v0u / l0, v1 = v1u / l1;
            const GVec3 b = v0.cross(v1);
            const float bl = b.length();
            const GVec3 o1 = bl > 0.0f ? (b / bl).cross(v0) : GVec3(0.0f, 0.0f, 0.0f);
            const float a0 = v0.dot(bconeAxis), a1 = o1.dot(bconeAxis);
            const float len = sqrtf(a0 * a0 + a1 * a1);
            const float cosPhi0 = len > 0.0f ? a0 / len : 1.0f;
            if (a1 < 0.0f || v0.dot(v1) > cosPhi0 || !(len > 0.0f))
                v = (a0 > v1.dot(bconeAxis)) ? v0 : v1;
            else
                v = v0 * cosPhi0 + o1 * (a1 / len);
        }
        pointToCentroidNorm = v * -1.0f;
        const float dc2 = (closestPoint - centroid).length2();
        const float r2 = bboxRadius * bboxRadius;
        cosSubtendedAngle = (dc2 <= r2) ? -1.0f : sqrtf(fmaxf(0.0f, 1.0f - r2 / dc2));
        clampedDistance = fmaxf(0.5f * bboxRadius, distance);
    }
    float sinSubtendedAngle = sqrtf(fmaxf(0.0f, 1.0f - cosSubtendedAngle * cosSubtendedAngle));
    GVec3 negPointToCentroid = pointToCentroidNorm * -1.0f;
    float cosTheta = bconeAxis.dot(negPointToCentroid);
    float sinTheta = sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta));
    float cosThetaMinusSubtended = cosTheta * cosSubtendedAngle + sinTheta * sinSubtendedAngle;
    float cosThetaO = cosf(thetaO);
    float sinThetaO = sinf(thetaO);
    float cosMinOutgoingAngle;
    if (cosTheta >= cosSubtendedAngle || cosThetaMinusSubtended >= cosThetaO) {
        cosMinOutgoingAngle = 1.0f;
    } else if ((thetaO + thetaE > M_PI_F) ||
               (cosThetaMinusSubtended > cosf(thetaO + thetaE))) {
        float sinThetaMinusSubtended = sqrtf(fmaxf(0.0f, 1.0f - cosThetaMinusSubtended * cosThetaMinusSubtended));
        cosMinOutgoingAngle = cosThetaMinusSubtended * cosThetaO + sinThetaMinusSubtended * sinThetaO;
    } else {
        return 0.0f;
    }
    // No incidence term, theta_d/d, min importance 0 (Cycles in_volume_segment).
    return fabsf(energy * cosMinOutgoingAngle * thetaD / clampedDistance);
}

// Leaf probability with the segment importance (min importance 0, so the min
// term is uniform over emitters with max importance > 0).
__device__ inline float gpu_light_tree_leaf_prob_seg(
    const GLightTreeView& view, const GLightTreeNode& leaf, int target,
    const GVec3& o, const GVec3& d, float t)
{
    float sumMax = 0.0f, tMax = 0.0f;
    int numHas = 0;
    for (int i = leaf.firstEmitter; i < leaf.firstEmitter + leaf.numEmitters; ++i) {
        const GLightTreeEmitter& e = view.emitters[i];
        float mx = gpu_light_tree_importance_seg(e.bboxMin, e.bboxMax, e.bconeAxis,
                                                 e.thetaO, e.thetaE, e.energy, o, d, t);
        sumMax += mx;
        numHas += (mx > 0.0f) ? 1 : 0;
        if (i == target) tMax = mx;
    }
    if (!(sumMax > 0.0f) || !(tMax > 0.0f)) return 0.0f;
    return 0.5f * (tMax / sumMax + 1.0f / (float)numHas);
}

// Mirror of LightTree::pickSegment (pickWith + segment importance).
__device__ inline int gpu_light_tree_pick_segment(
    const GLightTreeView& view, const GVec3& o, const GVec3& d, float t,
    float u, float* outPdf)
{
    if (!view.enabled || view.numNodes == 0) { *outPdf = 0.f; return -1; }
    int nodeIdx = 0;
    float pdf = 1.0f;
    while (!(view.nodes[nodeIdx].firstEmitter >= 0)) {
        const GLightTreeNode& node  = view.nodes[nodeIdx];
        const GLightTreeNode& left  = view.nodes[node.leftChild];
        const GLightTreeNode& right = view.nodes[node.rightChild];
        float leftImp = gpu_light_tree_importance_seg(left.bboxMin, left.bboxMax, left.bconeAxis,
                                                      left.thetaO, left.thetaE, left.energy, o, d, t);
        float rightImp = gpu_light_tree_importance_seg(right.bboxMin, right.bboxMax, right.bconeAxis,
                                                       right.thetaO, right.thetaE, right.energy, o, d, t);
        float totalImp = leftImp + rightImp;
        if (!(totalImp > 0.0f)) {
            *outPdf = 0.f;
            return -1;
        } else {
            float leftProb = leftImp / totalImp;
            if (u < leftProb) {
                nodeIdx = node.leftChild;
                pdf *= leftProb;
                u = u / leftProb;
            } else {
                nodeIdx = node.rightChild;
                pdf *= (1.0f - leftProb);
                u = (u - leftProb) / (1.0f - leftProb);
            }
        }
    }
    // Leaf: two reservoirs; the min one is uniform over lit emitters (min = 0),
    // the CPU pickWith fallback with every min importance 0.
    const GLightTreeNode& leaf = view.nodes[nodeIdx];
    int emitterIdx = -1;
    float selMax = 0.0f, totMax = 0.0f;
    int numHas = 0;
    const bool sampleMax = (u > 0.5f);
    if (leaf.numEmitters > 1) u = u * 2.0f - (sampleMax ? 1.0f : 0.0f);
    float w = 0.0f, tw = 0.0f;
    for (int i = leaf.firstEmitter; i < leaf.firstEmitter + leaf.numEmitters; ++i) {
        const GLightTreeEmitter& e = view.emitters[i];
        float mx = gpu_light_tree_importance_seg(e.bboxMin, e.bboxMax, e.bconeAxis,
                                                 e.thetaO, e.thetaE, e.energy, o, d, t);
        if (sampleMax) {
            gpu_light_tree_reservoir(i, mx, &emitterIdx, &selMax, &totMax, &u);
        } else {
            gpu_light_tree_reservoir(i, mx > 0.0f ? 1.0f : 0.0f, &emitterIdx, &w, &tw, &u);
            if (emitterIdx == i) selMax = mx;
            totMax += mx;
        }
        numHas += (mx > 0.0f) ? 1 : 0;
    }
    if (numHas == 0 || emitterIdx < 0) { *outPdf = 0.f; return -1; }
    *outPdf = pdf * 0.5f * (selMax / totMax + 1.0f / (float)numHas);
    return emitterIdx;
}

// Mirror of LightTree::pdfSegment (bit-trail walk, segment importance).
__device__ inline float gpu_light_tree_pdf_segment(
    const GLightTreeView& view, const GVec3& o, const GVec3& d, float t, int emitterIdx)
{
    if (!view.enabled || view.numNodes == 0 || emitterIdx < 0) return 0.f;
    unsigned int trail = view.emitters[emitterIdx].bitTrail;
    float pdf = 1.0f;
    int nodeIdx = 0;
    while (!(view.nodes[nodeIdx].firstEmitter >= 0)) {
        const GLightTreeNode& node  = view.nodes[nodeIdx];
        const GLightTreeNode& left  = view.nodes[node.leftChild];
        const GLightTreeNode& right = view.nodes[node.rightChild];
        float leftImp = gpu_light_tree_importance_seg(left.bboxMin, left.bboxMax, left.bconeAxis,
                                                      left.thetaO, left.thetaE, left.energy, o, d, t);
        float rightImp = gpu_light_tree_importance_seg(right.bboxMin, right.bboxMax, right.bconeAxis,
                                                       right.thetaO, right.thetaE, right.energy, o, d, t);
        float totalImp = leftImp + rightImp;
        bool goLeft = (trail & 1u) == 0u;
        trail >>= 1;
        if (!(totalImp > 0.0f)) return 0.f;  // #961 review: the pick fails here
        {
            float leftProb = leftImp / totalImp;
            pdf *= goLeft ? leftProb : (1.0f - leftProb);
        }
        nodeIdx = goLeft ? node.leftChild : node.rightChild;
    }
    return pdf * gpu_light_tree_leaf_prob_seg(view, view.nodes[nodeIdx], emitterIdx, o, d, t);
}
