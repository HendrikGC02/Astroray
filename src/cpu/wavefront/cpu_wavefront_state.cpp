// pkg55 Phase B' Session 2c — CPU wavefront SoA pack/unpack.
//
// Byte-exact round-trip of the shared-kernel PathState through the SoA.
// The RNG is carried as its four POD members and reconstructed to the
// IDENTICAL stream position (same dimension counter the oracle consumes).
// The already-normalized ray direction is restored verbatim — never
// renormalized at the stage boundary (Phase A.1 ulp-bug fix).

#include "raytracer.h"
#include "cpu_wavefront_state.h"

namespace astroray {
namespace cpu_wavefront {

void CPUWavefrontState::pack_from(int i, const PathState& ps) {
    pixel_index[i]  = ps.pixel_index;
    sample_index[i] = ps.sample_index;
    bounce[i]       = ps.bounce;

    // Live RNG state — the auto-incrementing stream, carried exactly.
    rng_pixel[i]     = ps.rng.pixel();
    rng_sample[i]    = ps.rng.sample();
    rng_dimension[i] = ps.rng.dimension();
    rng_seed[i]      = ps.rng.seed();

    ray_origin_x[i] = ps.ray_origin.x;
    ray_origin_y[i] = ps.ray_origin.y;
    ray_origin_z[i] = ps.ray_origin.z;
    // Already-normalized; stored verbatim.
    ray_direction_x[i] = ps.ray_direction.x;
    ray_direction_y[i] = ps.ray_direction.y;
    ray_direction_z[i] = ps.ray_direction.z;

    throughput_0[i] = ps.throughput[0];
    throughput_1[i] = ps.throughput[1];
    throughput_2[i] = ps.throughput[2];
    throughput_3[i] = ps.throughput[3];

    lambda_0[i] = ps.lambdas.lambda(0);
    lambda_1[i] = ps.lambdas.lambda(1);
    lambda_2[i] = ps.lambdas.lambda(2);
    lambda_3[i] = ps.lambdas.lambda(3);
    lambda_pdf_0[i] = ps.lambdas.pdf(0);
    lambda_pdf_1[i] = ps.lambdas.pdf(1);
    lambda_pdf_2[i] = ps.lambdas.pdf(2);
    lambda_pdf_3[i] = ps.lambdas.pdf(3);

    color_0[i] = ps.color[0];
    color_1[i] = ps.color[1];
    color_2[i] = ps.color[2];
    color_3[i] = ps.color[3];

    was_specular[i] = ps.wasSpecular ? 1 : 0;
    path_alive[i]   = ps.alive ? 1 : 0;
    bsdf_pdf_prev[i] = ps.bsdfPdfPrev;  // pkg120
}

PathState CPUWavefrontState::unpack_to(int i) const {
    // Reconstruct the RNG to the EXACT carried stream position. The ctor
    // sets dimension_=0; setDimension restores the carried counter so the
    // next draw is byte-identical to the oracle's single auto-incrementing
    // stream.
    PathState ps(rng_pixel[i], rng_sample[i], rng_seed[i]);
    ps.rng.setDimension(rng_dimension[i]);

    ps.pixel_index  = pixel_index[i];
    ps.sample_index = sample_index[i];
    ps.bounce       = bounce[i];

    ps.ray_origin    = Vec3(ray_origin_x[i], ray_origin_y[i], ray_origin_z[i]);
    // Restore the already-normalized direction verbatim — NO renormalize.
    ps.ray_direction = Vec3(ray_direction_x[i], ray_direction_y[i], ray_direction_z[i]);

    ps.throughput = SampledSpectrum(std::array<float, 4>{
        throughput_0[i], throughput_1[i], throughput_2[i], throughput_3[i]});
    ps.lambdas = SampledWavelengths::fromLambdas(
        std::array<float, 4>{lambda_0[i], lambda_1[i], lambda_2[i], lambda_3[i]},
        std::array<float, 4>{lambda_pdf_0[i], lambda_pdf_1[i], lambda_pdf_2[i], lambda_pdf_3[i]});
    ps.color = SampledSpectrum(std::array<float, 4>{
        color_0[i], color_1[i], color_2[i], color_3[i]});

    ps.wasSpecular = was_specular[i] != 0;
    ps.alive       = path_alive[i] != 0;
    ps.bsdfPdfPrev = bsdf_pdf_prev[i];  // pkg120
    return ps;
}

}  // namespace cpu_wavefront
}  // namespace astroray
