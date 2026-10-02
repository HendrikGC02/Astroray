// gpu_shade_noinline.h - pkg300: the out-of-line marker of the device functions
// reachable from the wavefront shade kernel. It is __noinline__ everywhere except the
// fleet shade TU (src/gpu/wavefront/shade_force_inline.cuh defines it first to
// force-inline them under a register cap). A project macro, not a redefinition of
// __noinline__, so system headers that spell __attribute__((__noinline__)) are
// unaffected.
#pragma once
#ifndef ASTRORAY_SHADE_NOINLINE
#define ASTRORAY_SHADE_NOINLINE __noinline__
#endif
