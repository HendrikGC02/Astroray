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

// Mirror of LightTree::importance (src/light_tree.cpp:388-469; Cycles
// light_tree_importance, kernel/light/tree.h). Keep the float math IDENTICAL
// to the CPU reference — the pkg86-B parity gate compares pick decisions.
__device__ inline float gpu_light_tree_importance(
    const GLightTreeNode& node, const GVec3& point, const GVec3& normal)
{
    GVec3 centroid = (node.bboxMin + node.bboxMax) * 0.5f;
    GVec3 pointToCentroid = centroid - point;
    float distance = pointToCentroid.length();
    if (distance < 1e-6f) distance = 1e-6f;
    GVec3 pointToCentroidNorm = pointToCentroid / distance;

    // Subtended half-angle of the cluster's bounding sphere.
    float bboxRadius = (node.bboxMax - centroid).length();
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
    if (cosMinIncidenceAngle < 0.0f) return 0.0f;  // cluster behind surface

    // Angle between cluster axis and emission direction toward the point.
    GVec3 negPointToCentroid = pointToCentroidNorm * -1.0f;
    float cosTheta = node.bconeAxis.dot(negPointToCentroid);
    float sinTheta = sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta));

    float cosThetaMinusSubtended = cosTheta * cosSubtendedAngle + sinTheta * sinSubtendedAngle;

    // Cone-cone visibility test (cos_min_outgoing_angle).
    float cosThetaO = cosf(node.thetaO);
    float sinThetaO = sinf(node.thetaO);

    float cosMinOutgoingAngle;
    if (cosTheta >= cosSubtendedAngle || cosThetaMinusSubtended >= cosThetaO) {
        cosMinOutgoingAngle = 1.0f;
    } else if ((node.thetaO + node.thetaE > M_PI_F) ||
               (cosThetaMinusSubtended > cosf(node.thetaO + node.thetaE))) {
        float sinThetaMinusSubtended = sqrtf(fmaxf(0.0f, 1.0f - cosThetaMinusSubtended * cosThetaMinusSubtended));
        cosMinOutgoingAngle = cosThetaMinusSubtended * cosThetaO + sinThetaMinusSubtended * sinThetaO;
    } else {
        return 0.0f;  // cluster invisible from this shading point
    }

    float minDistance = fmaxf(distance - bboxRadius, 1e-6f);
    return node.energy * cosMinIncidenceAngle * cosMinOutgoingAngle / (minDistance * minDistance);
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

    const GLightTreeNode& leaf = view.nodes[nodeIdx];
    int emitterIdx = leaf.firstEmitter + (int)(u * leaf.numEmitters);
    int last = leaf.firstEmitter + leaf.numEmitters - 1;
    if (emitterIdx > last) emitterIdx = last;

    *outPdf = pdf / (float)leaf.numEmitters;
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

    return pdf / (float)view.nodes[nodeIdx].numEmitters;
}
