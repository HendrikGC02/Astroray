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
    GVec3 pointToCentroid = centroid - point;
    float distance = pointToCentroid.length();
    if (distance < 1e-6f) distance = 1e-6f;
    GVec3 pointToCentroidNorm = pointToCentroid / distance;

    // Subtended half-angle of the cluster's bounding sphere.
    float bboxRadius = (bboxMax - centroid).length();
    float distanceSq = distance * distance;
    float radiusSq = bboxRadius * bboxRadius;

    float cosSubtendedAngle;
    if (distanceSq <= radiusSq) {
        cosSubtendedAngle = -1.0f;  // point inside bounding sphere
    } else {
        float sinSubtendedAngleSq = radiusSq / distanceSq;
        cosSubtendedAngle = sqrtf(1.0f - sinSubtendedAngleSq);
    }
    float sinSubtendedAngle = sqrtf(fmaxf(0.0f, 1.0f - cosSubtendedAngle * cosSubtendedAngle));

    float cosThetaI = pointToCentroidNorm.dot(normal);
    float sinThetaI = sqrtf(fmaxf(0.0f, 1.0f - cosThetaI * cosThetaI));

    // cos_min_incidence_angle = cos(max{theta_i - theta_u, 0}).
    float cosMinIncidenceAngle;
    if (cosThetaI >= cosSubtendedAngle) {
        cosMinIncidenceAngle = 1.0f;
    } else {
        cosMinIncidenceAngle = cosThetaI * cosSubtendedAngle + sinThetaI * sinSubtendedAngle;
    }
    if (cosMinIncidenceAngle < 0.0f) return;  // cluster behind surface
    float cosMaxIncidenceAngle =
        fmaxf(cosThetaI * cosSubtendedAngle - sinThetaI * sinSubtendedAngle, 0.0f);

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

    // #851: Cycles distance clamp (light_tree_node_importance), see CPU mirror.
    float clampedDistance = fmaxf(0.5f * bboxRadius, distance);
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

// Mirror of LightTree::leafEmitterProb (#851; Cycles
// light_tree_cluster_select_emitter): 0.5 * (max_i/sum(max) + min_i/sum(min)),
// min term uniform over max>0 emitters when sum(min) == 0; uniform when all max == 0.
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
    if (!(sumMax > 0.0f)) return 1.0f / (float)leaf.numEmitters;
    if (!(tMax > 0.0f)) return 0.0f;
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

        if (totalImp < 1e-8f) {
            nodeIdx = node.leftChild;  // both zero: pick left arbitrarily
            pdf *= 0.5f;
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

    // #851: leaf pick by the importance mixture (mirror of CPU pick()).
    const GLightTreeNode& leaf = view.nodes[nodeIdx];
    int emitterIdx = -1;
    float emitterProb = 0.0f, cdf = 0.0f;
    for (int i = leaf.firstEmitter; i < leaf.firstEmitter + leaf.numEmitters; ++i) {
        float p = gpu_light_tree_leaf_prob(view, leaf, i, point, normal);
        if (!(p > 0.0f)) continue;
        emitterIdx = i;
        emitterProb = p;
        cdf += p;
        if (u < cdf) break;
    }
    if (emitterIdx < 0) { *outPdf = 0.f; return -1; }

    *outPdf = pdf * emitterProb;
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

        if (totalImp < 1e-8f) {
            pdf *= 0.5f;
        } else {
            float leftProb = leftImp / totalImp;
            pdf *= goLeft ? leftProb : (1.0f - leftProb);
        }
        nodeIdx = goLeft ? node.leftChild : node.rightChild;
    }

    return pdf * gpu_light_tree_leaf_prob(view, view.nodes[nodeIdx], emitterIdx, point, normal);
}
